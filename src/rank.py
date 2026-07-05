"""Rank article candidates by relevance using Ollama (OpenAI-compatible API)."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime

from src.geo_diversity import diversify_ranked, geo_diversity_enabled
from src.llm import chat_json
from src.text_utils import strip_html

logger = logging.getLogger(__name__)

RELEVANCE_THRESHOLD = 32
TOP_N = 5
MAX_TO_RANK = 20

RELEVANCE_TOPIC = (
    "impact of AI on labor, workers, and industries — including jobs, employment, "
    "wages, workforce displacement, reskilling, unions, labor policy, automation, "
    "robotics, gig work, manufacturing, retail, logistics, creative work, and "
    "workplace technology."
)

RANK_JSON_INSTRUCTION = """\
Respond with JSON only:
{"rankings": [{"index": 0, "score": 85, "reason": "brief reason"}, ...]}
Use zero-based index matching [0], [1], ... in the user message.
Score 0-100 for relevance to AI's impact on jobs, workers, and industries.
Articles about AI plus jobs, workers, hiring, wages, automation, unions, or
industry/workplace change score 45+. Sector-specific labor stories (manufacturing,
retail, logistics, creative, tech) score 40+ when AI is involved.
Generic tech product news without labor angle scores below 35.\
"""

LABOR_KEYWORDS = re.compile(
    r"\b(ai|artificial intelligence|machine learning|generative ai|chatgpt|"
    r"labor|labour|jobs?|employment|workers?|workforce|workplace|"
    r"wages?|salary|salaries|hiring|layoff|layoffs|redundan|"
    r"automation|robot|robotics|union|strike|gig economy|freelance|"
    r"industr(?:y|ies)|manufacturing|warehouse|retail|clerical|"
    r"white.?collar|blue.?collar|reskill|upskill|job market|staffing)\b",
    re.I,
)


@dataclass
class RankedArticle:
    headline: str
    url: str
    score: int
    reason: str
    text: str
    snippet: str = ""
    published: datetime | None = None
    source: str = ""
    search_region: str = ""
    publisher_country: str = ""
    thematic_region: str = ""
    concepts: tuple[str, ...] = ()
    companies: tuple[str, ...] = ()


def _ranked_from_candidate(
    c: dict,
    *,
    score: int,
    reason: str,
) -> RankedArticle:
    return RankedArticle(
        headline=c["headline"],
        url=c["url"],
        score=score,
        reason=reason,
        text=c.get("text") or c.get("snippet") or "",
        snippet=c.get("snippet") or "",
        published=c.get("published"),
        source=c.get("source") or "",
        search_region=c.get("search_region") or "",
        publisher_country=c.get("publisher_country") or "",
        thematic_region=c.get("thematic_region") or "",
        concepts=tuple(c.get("concepts") or ()),
        companies=tuple(c.get("companies") or ()),
    )


def _select_top(
    scored: list[RankedArticle],
    top_n: int,
    *,
    geographic_regions: tuple[str, ...] = (),
) -> list[RankedArticle]:
    from src.thematic_regions import normalize_region_selection

    selected = normalize_region_selection(list(geographic_regions))
    # Only force geographic round-robin when the user explicitly picks regions;
    # in Global mode we keep pure relevance order.
    if geo_diversity_enabled() and selected and scored:
        from src.thematic_regions import resolve_pick_order

        return diversify_ranked(
            scored,
            top_n,
            pick_order=resolve_pick_order(geographic_regions),
        )
    return scored[:top_n]


REGION_RANK_BOOST = int(os.environ.get("REGION_RANK_BOOST", "20"))


def _region_boost_labels(geographic_regions: tuple[str, ...]) -> set[str]:
    """Display labels for explicitly selected regions (empty = Global, no boost)."""
    from src.thematic_regions import THEMATIC_REGIONS, normalize_region_selection

    ids = normalize_region_selection(list(geographic_regions))
    return {THEMATIC_REGIONS[i].label for i in ids if i in THEMATIC_REGIONS}


def _apply_region_boost(
    candidate: dict, score: int, boost_labels: set[str]
) -> int:
    if boost_labels and candidate.get("thematic_region") in boost_labels:
        return min(score + REGION_RANK_BOOST, 100)
    return score


def _threshold() -> int:
    return int(os.environ.get("RELEVANCE_THRESHOLD", str(RELEVANCE_THRESHOLD)))


def rank_use_er_score() -> bool:
    """Use Event Registry relevance ordering instead of LLM ranking (matches ER export quality)."""
    return os.environ.get("RANK_USE_ER_SCORE", "").strip() == "1"


def rank_by_eventregistry_score(
    candidates: list[dict],
    *,
    top_n: int,
    geographic_regions: tuple[str, ...] = (),
) -> list[RankedArticle]:
    """Rank by Event Registry relevance score + regional boost + geo-diversity."""
    boost_labels = _region_boost_labels(geographic_regions)
    scored: list[tuple[int, RankedArticle]] = []
    for c in candidates:
        try:
            raw = float(c.get("relevance_score") or 0)
        except (TypeError, ValueError):
            raw = 0.0
        # ER relevance is typically ~100–600; map to 1–100 for boost/diversity.
        base = min(100, max(1, int(raw / 6))) if raw > 0 else 50
        boosted = _apply_region_boost(c, base, boost_labels)
        scored.append(
            (
                boosted,
                _ranked_from_candidate(
                    c,
                    score=boosted,
                    reason="Event Registry relevance",
                ),
            )
        )
    scored.sort(key=lambda x: x[0], reverse=True)
    articles = [article for _, article in scored]
    top = _select_top(articles, top_n, geographic_regions=geographic_regions)
    logger.info("Event Registry score ranking selected %d articles", len(top))
    return top


def _preview_chars() -> int:
    return int(os.environ.get("RANK_PREVIEW_CHARS", "500"))


def _preview_text(candidate: dict) -> str:
    raw = candidate.get("text") or candidate.get("snippet") or ""
    cleaned = strip_html(str(raw))
    if cleaned:
        return cleaned[: _preview_chars()]
    return candidate.get("headline", "")[:500]


def _normalize_index(raw_index: int, count: int) -> int | None:
    """Accept 0-based or 1-based indices from the model."""
    if 0 <= raw_index < count:
        return raw_index
    if 1 <= raw_index <= count:
        return raw_index - 1
    return None


def _parse_rankings(parsed: dict, to_rank: list[dict]) -> list[tuple[int, dict]]:
    """Extract (score, item) pairs from assorted LLM JSON shapes."""
    rows = parsed.get("rankings") or parsed.get("articles") or parsed.get("scores") or []
    if isinstance(rows, dict):
        rows = [{"index": int(k), "score": v} for k, v in rows.items() if str(k).isdigit()]

    results: list[tuple[int, dict]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        raw_idx = item.get("index", item.get("article_index", item.get("id")))
        if raw_idx is None:
            continue
        idx = _normalize_index(int(raw_idx), len(to_rank))
        if idx is None:
            continue
        try:
            score = int(item.get("score", item.get("relevance", 0)))
        except (TypeError, ValueError):
            continue
        results.append((score, {**item, "index": idx, "score": score}))
    return results


def _keyword_fallback(
    to_rank: list[dict],
    *,
    top_n: int,
    geographic_regions: tuple[str, ...] = (),
) -> list[RankedArticle]:
    """Use keyword overlap when the LLM returns no passing articles."""
    scored: list[tuple[int, int, dict]] = []
    for i, c in enumerate(to_rank):
        blob = f"{c.get('headline', '')} {_preview_text(c)}"
        hits = len(LABOR_KEYWORDS.findall(blob))
        if hits:
            scored.append((hits, i, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[RankedArticle] = []
    for hits, _, c in scored:
        out.append(
            _ranked_from_candidate(
                c,
                score=40 + min(hits * 10, 50),
                reason="Keyword match (LLM ranking unavailable or too strict)",
            )
        )
    out = _select_top(out, top_n, geographic_regions=geographic_regions)
    logger.info("Keyword fallback selected %d articles", len(out))
    return out


def rank_articles(
    candidates: list[dict],
    *,
    top_n: int = TOP_N,
    max_to_rank: int = MAX_TO_RANK,
    relevance_threshold: int | None = None,
    geographic_regions: tuple[str, ...] = (),
) -> list[RankedArticle]:
    """Score and return top articles by relevance."""
    if not candidates:
        return []

    threshold = relevance_threshold if relevance_threshold is not None else _threshold()
    to_rank = candidates[:max_to_rank]

    if os.environ.get("RANK_LLM", "0").strip() == "0":
        return _keyword_fallback(
            to_rank,
            top_n=top_n,
            geographic_regions=geographic_regions,
        )

    articles_block = []
    for i, c in enumerate(to_rank):
        preview = _preview_text(c)
        articles_block.append(
            f"[{i}] Headline: {c['headline']}\n"
            f"URL: {c['url']}\n"
            f"Text preview:\n{preview or '(headline only)'}\n"
        )

    prompt = (
        f"Evaluate relevance to: {RELEVANCE_TOPIC}\n\n"
        + "\n---\n".join(articles_block)
    )

    try:
        parsed = chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You score news for AI labor-market relevance. "
                        + RANK_JSON_INSTRUCTION
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=min(2048, 50 * len(to_rank) + 256),
        )
    except Exception as exc:
        logger.warning("LLM ranking failed (%s), using keyword fallback", exc)
        return _keyword_fallback(
            to_rank,
            top_n=top_n,
            geographic_regions=geographic_regions,
        )

    parsed_rows = _parse_rankings(parsed, to_rank)
    if not parsed_rows:
        logger.warning("LLM returned no rankings: %s", list(parsed.keys()))
        return _keyword_fallback(
            to_rank,
            top_n=top_n,
            geographic_regions=geographic_regions,
        )

    boost_labels = _region_boost_labels(geographic_regions)

    # Apply the regional boost once, then reuse for both the threshold pass and
    # the below-threshold fallback so ordering is consistent.
    boosted: list[tuple[int, RankedArticle]] = []
    for score, meta in parsed_rows:
        idx = meta["index"]
        c = to_rank[idx]
        bscore = _apply_region_boost(c, score, boost_labels)
        boosted.append(
            (
                bscore,
                _ranked_from_candidate(c, score=bscore, reason=str(meta.get("reason", ""))),
            )
        )

    scored = [pair for pair in boosted if pair[0] >= threshold]
    scored.sort(key=lambda x: x[0], reverse=True)
    top = _select_top(
        [article for _, article in scored],
        top_n,
        geographic_regions=geographic_regions,
    )

    if not top:
        logger.warning(
            "No articles above threshold %d (parsed %d scores), using fallback",
            threshold,
            len(parsed_rows),
        )
        # Take best available scores even if below threshold.
        scored_all = sorted(boosted, key=lambda x: x[0], reverse=True)
        top = _select_top(
            [a for _, a in scored_all],
            top_n,
            geographic_regions=geographic_regions,
        )

    if not top:
        top = _keyword_fallback(
            to_rank,
            top_n=top_n,
            geographic_regions=geographic_regions,
        )

    logger.info(
        "Ranked %d candidates, %d above threshold %d, returning %d",
        len(to_rank),
        len(scored),
        threshold,
        len(top),
    )
    return top

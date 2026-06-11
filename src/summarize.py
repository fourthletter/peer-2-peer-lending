"""Generate 2-5 sentence summaries via Ollama (OpenAI-compatible API)."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime

from src.llm import chat_json
from src.rank import RankedArticle
from src.text_utils import strip_html

logger = logging.getLogger(__name__)

MIN_SUMMARY_LEN = 40


def _summary_text_chars() -> int:
    return int(os.environ.get("SUMMARY_TEXT_CHARS", "1800"))


def _llm_retry_enabled() -> bool:
    return os.environ.get("SUMMARY_LLM_RETRY", "1") == "1"


def llm_summary_enabled() -> bool:
    """False when SUMMARY_LLM=0 — use headline + discovery snippet only (no Ollama)."""
    return os.environ.get("SUMMARY_LLM", "1") != "0"

SUMMARY_JSON_INSTRUCTION = """\
Respond with JSON only, in this exact shape:
{
  "articles": [
    {
      "headline": "article headline",
      "url": "https://...",
      "summary": "2 to 5 factual sentences."
    }
  ]
}
Each summary must be exactly 2 to 5 complete sentences.\
"""


def _summary_ok(text: str) -> bool:
    return len((text or "").strip()) >= MIN_SUMMARY_LEN


def _has_source_text(article: RankedArticle) -> bool:
    clean = strip_html(article.text or "").strip()
    return bool(clean) and clean != "(no full text available)" and len(clean) >= 80


def _extractive_summary(text: str, *, max_sentences: int = 3) -> str:
    """First few sentences from article body when the LLM returns nothing."""
    clean = strip_html(text).strip()
    if not clean or clean == "(no full text available)":
        return ""

    sentences: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+", clean):
        part = part.strip()
        if len(part) < 25:
            continue
        sentences.append(part)
        if len(sentences) >= max_sentences:
            break

    if sentences:
        return " ".join(sentences)

    if len(clean) > 400:
        return clean[:397].rsplit(" ", 1)[0] + "..."
    return clean


def _snippet_summary(article: RankedArticle) -> str:
    """Headline plus discovery snippet (Event Registry body, NewsAPI blurb, etc.)."""
    headline = (article.headline or "").strip().rstrip(".")
    raw = strip_html(article.snippet or article.text or "").strip()
    if not raw or raw == headline:
        return headline + "."

    extractive = _extractive_summary(raw, max_sentences=3)
    if _summary_ok(extractive):
        return f"{headline}. {extractive}"

    if len(raw) > 500:
        raw = raw[:497].rsplit(" ", 1)[0] + "..."
    return f"{headline}. {raw}"


def _headline_fallback(article: RankedArticle) -> str:
    parts = [article.headline.rstrip(".")]
    if article.reason:
        parts.append(article.reason.rstrip("."))
    parts.append(
        "See the publisher link for full coverage of AI and labor-market impacts."
    )
    return ". ".join(parts) + "."


def _summarize_one_llm(article: RankedArticle) -> str:
    """Retry a single article when batch summarization omits or truncates it."""
    limit = _summary_text_chars()
    text = (article.text or "")[:limit] if article.text else "(no full text available)"
    try:
        parsed = chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Write one factual 2-5 sentence summary about AI and labor. "
                        + SUMMARY_JSON_INSTRUCTION
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Headline: {article.headline}\nURL: {article.url}\n\n"
                        f"Article text:\n{text}"
                    ),
                },
            ],
            max_tokens=256,
        )
        items = parsed.get("articles", [])
        if items:
            summary = (items[0].get("summary") or "").strip()
            if _summary_ok(summary):
                return summary
    except Exception as exc:
        logger.warning("Single-article summary retry failed for %s: %s", article.url, exc)
    return ""


def _ensure_summary(article: RankedArticle, llm_summary: str) -> str:
    """Fill in summary from LLM output, extractive text, retry, or headline fallback."""
    summary = (llm_summary or "").strip()
    if _summary_ok(summary):
        return summary

    extractive = _extractive_summary(article.text or "")
    if _summary_ok(extractive):
        logger.info("Using extractive summary fallback for %s", article.url)
        return extractive

    if _llm_retry_enabled() and _has_source_text(article):
        retried = _summarize_one_llm(article)
        if _summary_ok(retried):
            logger.info("Using single-article LLM summary for %s", article.url)
            return retried

    extractive_retry = _extractive_summary(article.text or "", max_sentences=5)
    if _summary_ok(extractive_retry):
        logger.info("Using extended extractive summary for %s", article.url)
        return extractive_retry

    logger.warning("Using headline fallback summary for %s", article.url)
    return _headline_fallback(article)


@dataclass
class DigestArticle:
    headline: str
    url: str
    summary: str
    published: datetime | None = None
    source: str = ""
    publisher_country: str = ""
    search_region: str = ""
    thematic_region: str = ""
    concepts: tuple[str, ...] = ()
    companies: tuple[str, ...] = ()


def _summary_batch_size() -> int:
    """Articles per LLM summary call. Smaller batches = shorter, more reliable JSON."""
    return max(int(os.environ.get("SUMMARY_BATCH_SIZE", "4")), 1)


def _batch_summaries(chunk: list[RankedArticle]) -> dict[str, str]:
    """LLM summaries for a chunk, keyed by URL. Returns {} if the call/JSON fails."""
    limit = _summary_text_chars()
    blocks = []
    for i, a in enumerate(chunk):
        text = a.text[:limit] if a.text else "(no full text available)"
        blocks.append(
            f"[{i + 1}]\nHeadline: {a.headline}\nURL: {a.url}\n\nArticle text:\n{text}\n"
        )

    prompt = (
        "Write a factual summary for each article below. Each summary must be "
        "exactly 2 to 5 complete sentences. Focus on how AI affects jobs, workers, "
        "wages, hiring, displacement, reskilling, or labor policy. No hype or "
        "marketing language. Use the provided headline and URL in your output.\n\n"
        + "\n---\n".join(blocks)
    )

    try:
        parsed = chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "You write concise, factual news summaries about AI and labor "
                        "markets. " + SUMMARY_JSON_INSTRUCTION
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=min(2048, 200 * len(chunk) + 128),
        )
    except Exception as exc:  # malformed JSON / model error must not crash the digest
        logger.warning("Batch summary failed for %d articles: %s", len(chunk), exc)
        return {}

    parsed_items = parsed.get("articles", []) or []
    summaries: dict[str, str] = {}
    for i, ranked in enumerate(chunk):
        item = parsed_items[i] if i < len(parsed_items) else {}
        summary = (item.get("summary") or "").strip()
        if not summary:
            for candidate in parsed_items:  # LLM may reorder/drop — match by URL
                if candidate.get("url") == ranked.url:
                    summary = (candidate.get("summary") or "").strip()
                    break
        if summary:
            summaries[ranked.url] = summary
    return summaries


def summarize_articles(articles: list[RankedArticle]) -> list[DigestArticle]:
    """Produce digest blurbs for each article.

    Default: LLM summaries in small batches. With SUMMARY_LLM=0, uses headline
    plus the discovery snippet only (fast; best with Event Registry body text).
    """
    if not articles:
        return []

    if not llm_summary_enabled():
        logger.info(
            "SUMMARY_LLM=0: headline + discovery snippets for %d articles",
            len(articles),
        )
        return [
            DigestArticle(
                headline=ranked.headline,
                url=ranked.url,
                summary=_snippet_summary(ranked),
                published=ranked.published,
                source=ranked.source,
                publisher_country=ranked.publisher_country,
                search_region=ranked.search_region,
                thematic_region=ranked.thematic_region,
                concepts=ranked.concepts,
                companies=ranked.companies,
            )
            for ranked in articles
        ]

    batch = _summary_batch_size()
    llm_summaries: dict[str, str] = {}
    for start in range(0, len(articles), batch):
        llm_summaries.update(_batch_summaries(articles[start : start + batch]))

    results: list[DigestArticle] = []
    for ranked in articles:
        results.append(
            DigestArticle(
                headline=ranked.headline,
                url=ranked.url,
                summary=_ensure_summary(ranked, llm_summaries.get(ranked.url, "")),
                published=ranked.published,
                source=ranked.source,
                publisher_country=ranked.publisher_country,
                search_region=ranked.search_region,
                thematic_region=ranked.thematic_region,
                concepts=ranked.concepts,
                companies=ranked.companies,
            )
        )

    logger.info("Summarized %d articles", len(results))
    return results

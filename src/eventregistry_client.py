"""Optional Event Registry (newsapi.ai) discovery — 150k+ global sources.

Activates only when EVENTREGISTRY_API_KEY is set; otherwise returns no results so
the rest of the hybrid pipeline is unaffected. Get a key at https://eventregistry.org
(the free tier is token-limited, so we batch a few getArticles requests per run).
"""

from __future__ import annotations

import logging
import os
from datetime import date

import requests

from src.article import ArticleCandidate
from src.parse_dates import parse_published

logger = logging.getLogger(__name__)

EVENTREGISTRY_URL = "https://eventregistry.org/api/v1/article/getArticles"

_WIKI = "http://en.wikipedia.org/wiki/"

AI_CONCEPT = _WIKI + "Artificial_intelligence"
LABOR_CONCEPTS = (
    "Employment",
    "Labour_economics",
    "Layoff",
    "Workforce",
    "Unemployment",
    "Automation",
    "Job",
    "White-collar_worker",
)
LABOR_CATEGORY = "dmoz/Business/Employment"

# AI + creative rights / voice (ER concept + keyword OR — separate fetch, merged first).
CREATIVE_RIGHTS_CONCEPTS = (
    "Voice_acting",
    "Intellectual_property",
    "Plagiarism",
    "Copyright",
    "Entertainment",
)
CREATIVE_RIGHTS_KEYWORDS = (
    "voice actors",
    "Japanese voice actors",
    "unauthorized AI voice",
    "creative rights",
    "AI plagiarism",
)

# Garment, platform, delivery, informal / domestic work (second supplement fetch).
# ER free tier allows ~15 terms in one $or; keep concept + keyword count ≤ 15.
INFORMAL_WORKFORCE_CONCEPTS = (
    "Textile",
    "Clothing",
    "Amazon_(company)",
    "Uber",
    "Food_delivery",
    "Domestic_worker",
    "Nanny",
    "Maid",
)
INFORMAL_WORKFORCE_KEYWORDS = (
    "garment workers",
    "amazon warehouse",
    "uber drivers",
    "delivery workers",
    "street vendors",
    "nannies",
    "maids",
)


def _concept_label(concept: dict) -> str:
    label = concept.get("label") or {}
    if isinstance(label, dict):
        return (label.get("eng") or "").strip()
    return (label or "").strip() if isinstance(label, str) else ""


def _parse_er_metadata(article: dict) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    """Extract concept tags, company names, and country from Event Registry concepts."""
    concepts: list[str] = []
    companies: list[str] = []
    country = ""
    for item in article.get("concepts") or []:
        ctype = item.get("type") or ""
        name = _concept_label(item)
        if not name:
            continue
        if ctype == "org":
            companies.append(name)
        elif ctype == "loc":
            if not country:
                country = name
            concepts.append(name)
        elif ctype == "wiki":
            concepts.append(name)

    def _dedupe(items: list[str]) -> tuple[str, ...]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return tuple(out)

    return _dedupe(concepts), _dedupe(companies), country


def _query_mode() -> str:
    """ai_export = labor + broad AI (spreadsheet-style). ai_labor / ai = single query."""
    return os.environ.get("EVENTREGISTRY_QUERY_MODE", "ai_export").strip().lower()


def _sort_by() -> str:
    raw = os.environ.get("EVENTREGISTRY_SORT", "rel").strip().lower()
    return raw if raw in {"rel", "date", "sourceImportance"} else "rel"


def _country_uris(countries: list[str]) -> list[str]:
    return [_WIKI + name.replace(" ", "_") for name in countries]


def _location_uris_for_themes(theme_ids: list[str]) -> list[str]:
    from src.thematic_regions import THEMATIC_REGIONS

    countries: set[str] = set()
    for tid in theme_ids:
        region = THEMATIC_REGIONS.get(tid)
        if region and region.countries:
            countries.update(region.countries)
    # Event Registry OR clauses are large; cap country count per request.
    return _country_uris(sorted(countries)[:45])


def _topic_or_clause(
    *,
    concepts: tuple[str, ...],
    keywords: tuple[str, ...],
) -> dict:
    topic_or: list[dict] = [{"conceptUri": _WIKI + c} for c in concepts]
    topic_or.extend({"keyword": phrase} for phrase in keywords)
    return {"$or": topic_or}


def _build_query(
    date_from,
    date_to,
    *,
    mode: str,
    location_uris: list[str] | None = None,
) -> dict:
    """Concept-based query: AI + optional topic filter + optional source countries."""
    conditions: list[dict] = [
        {"conceptUri": AI_CONCEPT},
        {"lang": "eng"},
        {"dateStart": date_from.isoformat(), "dateEnd": date_to.isoformat()},
    ]
    if mode == "ai_creative":
        conditions.insert(
            1,
            _topic_or_clause(
                concepts=CREATIVE_RIGHTS_CONCEPTS,
                keywords=CREATIVE_RIGHTS_KEYWORDS,
            ),
        )
    elif mode == "ai_workforce":
        conditions.insert(
            1,
            _topic_or_clause(
                concepts=INFORMAL_WORKFORCE_CONCEPTS,
                keywords=INFORMAL_WORKFORCE_KEYWORDS,
            ),
        )
    elif mode != "ai":
        labor_or = [{"conceptUri": _WIKI + c} for c in LABOR_CONCEPTS]
        labor_or.append({"categoryUri": LABOR_CATEGORY})
        conditions.insert(1, {"$or": labor_or})
    if location_uris:
        conditions.append(
            {"$or": [{"sourceLocationUri": uri} for uri in location_uris]}
        )
    return {
        "query": {
            "$query": {"$and": conditions},
            "$filter": {"isDuplicate": "skipDuplicates"},
        }
    }


def _topic_supplement_enabled() -> bool:
    return os.environ.get("EVENTREGISTRY_TOPIC_SUPPLEMENT", "1") == "1"


def _creative_supplement_count(total: int) -> int:
    raw = os.environ.get("EVENTREGISTRY_CREATIVE_SUPPLEMENT", "18")
    return min(max(int(raw), 0), 30, total)


def _informal_work_supplement_count(total: int) -> int:
    raw = os.environ.get("EVENTREGISTRY_INFORMAL_WORK_SUPPLEMENT", "18")
    return min(max(int(raw), 0), 30, total)


def _articles_to_candidates(
    results: list[dict],
    *,
    search_region: str,
    limit: int,
) -> list[ArticleCandidate]:
    candidates: list[ArticleCandidate] = []
    for article in results:
        if len(candidates) >= limit:
            break
        url = (article.get("url") or "").strip()
        title = (article.get("title") or "").strip()
        if not url or not title:
            continue
        published = parse_published(article.get("dateTime") or article.get("date"))
        source = (article.get("source") or {}).get("title") or "Event Registry"
        body = (article.get("body") or "").strip()
        snippet = body[:1200] if body else ""
        concept_tags, company_tags, country = _parse_er_metadata(article)
        try:
            relevance = float(article.get("relevance") or article.get("wgt") or 0)
        except (TypeError, ValueError):
            relevance = 0.0
        candidates.append(
            ArticleCandidate(
                headline=title,
                url=url,
                published=published,
                source=source,
                snippet=snippet,
                search_region=search_region,
                provider="eventregistry",
                concepts=concept_tags,
                companies=company_tags,
                location_country=country,
                relevance_score=relevance,
            )
        )
    return candidates


def _merge_candidates(
    batches: list[list[ArticleCandidate]],
    *,
    max_total: int,
) -> list[ArticleCandidate]:
    seen: set[str] = set()
    merged: list[ArticleCandidate] = []
    for batch in batches:
        for c in batch:
            if c.url in seen:
                continue
            seen.add(c.url)
            merged.append(c)
            if len(merged) >= max_total:
                return merged
    return merged


def _fetch_articles(
    api_key: str,
    *,
    date_from,
    date_to,
    mode: str,
    count: int,
    location_uris: list[str] | None = None,
    search_region: str,
    sort_by: str | None = None,
) -> list[ArticleCandidate]:
    payload = {
        "apiKey": api_key,
        "resultType": "articles",
        "dataType": ["news", "pr"],
        "articlesSortBy": sort_by or _sort_by(),
        "articlesCount": min(max(count, 1), 100),
        "includeArticleConcepts": True,
        "includeArticleCategories": False,
        **_build_query(date_from, date_to, mode=mode, location_uris=location_uris),
    }

    try:
        resp = requests.post(EVENTREGISTRY_URL, json=payload, timeout=25)
    except requests.RequestException as exc:
        logger.warning("Event Registry request failed (%s): %s", mode, exc)
        return []

    if resp.status_code in (401, 429):
        logger.warning("Event Registry %s (%s); skipping.", resp.status_code, mode)
        return []

    try:
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Event Registry request failed (%s): %s", mode, exc)
        return []

    if isinstance(data, dict) and data.get("error"):
        logger.warning("Event Registry error (%s): %s", mode, data.get("error"))
        return []

    results = ((data or {}).get("articles") or {}).get("results") or []
    return _articles_to_candidates(results, search_region=search_region, limit=count)


def discover_eventregistry(
    query: str,
    *,
    date_from,
    date_to,
    max_results: int = 50,
    bucket_keys: list[str] | None = None,
    theme_region_keys: list[str] | None = None,
) -> list[ArticleCandidate]:
    """Discover AI news via Event Registry (concept queries, optional regional supplement)."""
    del query, bucket_keys  # concept query; NewsAPI buckets unused for ER

    api_key = os.environ.get("EVENTREGISTRY_API_KEY", "").strip()
    if not api_key:
        return []

    count = min(
        max(int(os.environ.get("EVENTREGISTRY_MAX_RESULTS", str(max_results))), 1),
        100,
    )
    mode = _query_mode()
    batches: list[list[ArticleCandidate]] = []

    if mode == "ai_export":
        creative_n = _creative_supplement_count(count) if _topic_supplement_enabled() else 0
        workforce_n = _informal_work_supplement_count(count) if _topic_supplement_enabled() else 0
        reserved = creative_n + workforce_n
        base = max(count - reserved, 2)
        labor_n = max(1, int(base * 0.65))
        ai_n = max(1, base - labor_n)
        if _topic_supplement_enabled():
            if creative_n:
                batches.append(
                    _fetch_articles(
                        api_key,
                        date_from=date_from,
                        date_to=date_to,
                        mode="ai_creative",
                        count=creative_n,
                        search_region="eventregistry:creative",
                    )
                )
            if workforce_n:
                batches.append(
                    _fetch_articles(
                        api_key,
                        date_from=date_from,
                        date_to=date_to,
                        mode="ai_workforce",
                        count=workforce_n,
                        search_region="eventregistry:workforce",
                    )
                )
        batches.append(
            _fetch_articles(
                api_key,
                date_from=date_from,
                date_to=date_to,
                mode="ai_labor",
                count=labor_n,
                search_region="eventregistry:labor",
            )
        )
        batches.append(
            _fetch_articles(
                api_key,
                date_from=date_from,
                date_to=date_to,
                mode="ai",
                count=ai_n,
                search_region="eventregistry:ai",
            )
        )
    else:
        er_mode = "ai" if mode == "ai" else "ai_labor"
        batches.append(
            _fetch_articles(
                api_key,
                date_from=date_from,
                date_to=date_to,
                mode=er_mode,
                count=count,
                search_region="eventregistry:global",
            )
        )

    # Merge order: regional → creative → informal workforce → labor → broad AI.
    # Earlier batches win dedupe slots so voice/garment/gig stories are not crowded out.
    ordered: list[list[ArticleCandidate]] = []

    regional_on = os.environ.get("EVENTREGISTRY_REGIONAL_SUPPLEMENT", "1") == "1"
    themes = [t for t in (theme_region_keys or []) if t and t != "global"]
    if regional_on and themes:
        uris = _location_uris_for_themes(themes)
        if uris:
            regional_n = min(24, max(10, count // 4))
            ordered.append(
                _fetch_articles(
                    api_key,
                    date_from=date_from,
                    date_to=date_to,
                    mode="ai_labor",
                    count=regional_n,
                    location_uris=uris,
                    search_region="eventregistry:regional",
                )
            )

    creative_batches = [
        b for b in batches if b and b[0].search_region == "eventregistry:creative"
    ]
    workforce_batches = [
        b for b in batches if b and b[0].search_region == "eventregistry:workforce"
    ]
    other_batches = [
        b
        for b in batches
        if not b
        or b[0].search_region
        not in {"eventregistry:creative", "eventregistry:workforce"}
    ]
    ordered.extend(creative_batches)
    ordered.extend(workforce_batches)
    ordered.extend(other_batches)

    candidates = _merge_candidates(ordered, max_total=count)
    logger.info(
        "Event Registry: %d candidates (mode=%s, fetches=%d)",
        len(candidates),
        mode,
        len(ordered),
    )
    return candidates


VIZ_HISTORY_START = date(2020, 1, 1)


def discover_eventregistry_viz(
    date_from: date,
    date_to: date,
    *,
    max_results: int = 100,
    theme_region_keys: list[str] | None = None,
) -> list[ArticleCandidate]:
    """Streamlined viz discovery: one primary labor query (+ optional regional supplement)."""
    api_key = os.environ.get("EVENTREGISTRY_API_KEY", "").strip()
    if not api_key:
        return []

    count = min(max(max_results, 1), 100)
    batches: list[list[ArticleCandidate]] = [
        _fetch_articles(
            api_key,
            date_from=date_from,
            date_to=date_to,
            mode="ai_labor",
            count=count,
            search_region="eventregistry:viz:live",
            sort_by="rel",
        )
    ]

    themes = [t for t in (theme_region_keys or []) if t and t != "global"]
    if themes and os.environ.get("EVENTREGISTRY_REGIONAL_SUPPLEMENT", "1") == "1":
        uris = _location_uris_for_themes(themes)
        if uris:
            regional_n = min(20, max(8, count // 5))
            batches.append(
                _fetch_articles(
                    api_key,
                    date_from=date_from,
                    date_to=date_to,
                    mode="ai_labor",
                    count=regional_n,
                    location_uris=uris,
                    search_region="eventregistry:viz:regional",
                    sort_by="rel",
                )
            )

    merged = _merge_candidates(batches, max_total=count)
    logger.info(
        "Event Registry viz (streamlined): %d candidates (%s – %s)",
        len(merged),
        date_from.isoformat(),
        date_to.isoformat(),
    )
    return merged


def fetch_viz_year_candidates(
    year: int,
    *,
    date_from: date,
    date_to: date,
    per_year: int,
    theme_region_keys: list[str] | None = None,
) -> list[ArticleCandidate]:
    """Single labor query for one calendar year (used by per-year disk cache)."""
    api_key = os.environ.get("EVENTREGISTRY_API_KEY", "").strip()
    if not api_key:
        return []

    y_from = max(date_from, date(year, 1, 1))
    y_to = min(date_to, date(year, 12, 31))
    if y_from > y_to:
        return []

    count = min(max(per_year, 1), 100)
    return _fetch_articles(
        api_key,
        date_from=y_from,
        date_to=y_to,
        mode="ai_labor",
        count=count,
        search_region=f"eventregistry:viz:{year}",
        sort_by="date",
    )


def discover_viz_yearly_samples(
    date_from: date,
    date_to: date,
) -> list[ArticleCandidate]:
    """One Event Registry pull per calendar year for charts spanning 2020–present."""
    if os.environ.get("EVENTREGISTRY_VIZ_YEARLY", "1") != "1":
        return []
    api_key = os.environ.get("EVENTREGISTRY_API_KEY", "").strip()
    if not api_key:
        return []

    start = max(date_from, VIZ_HISTORY_START)
    if (date_to - start).days < 400:
        return []

    per_year = max(6, int(os.environ.get("EVENTREGISTRY_VIZ_PER_YEAR", "12")))
    cap = max(50, int(os.environ.get("EVENTREGISTRY_VIZ_YEARLY_MAX", "120")))
    batches: list[list[ArticleCandidate]] = []

    for year in range(start.year, date_to.year + 1):
        y_from = max(start, date(year, 1, 1))
        y_to = min(date_to, date(year, 12, 31))
        half = max(3, per_year // 2)
        # Labor-tagged stories are sparse before ~2025; also pull broad AI per year.
        for mode in ("ai_labor", "ai"):
            batch = _fetch_articles(
                api_key,
                date_from=y_from,
                date_to=y_to,
                mode=mode,
                count=half,
                search_region=f"eventregistry:viz:{year}:{mode}",
                sort_by="date",
            )
            if batch:
                batches.append(batch)

    merged = _merge_candidates(batches, max_total=cap)
    logger.info("Event Registry viz history: %d articles (%d years)", len(merged), len(batches))
    return merged

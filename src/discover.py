"""Discover articles via parallel DuckDuckGo news search (ddgs)."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

from ddgs import DDGS

from src.article import ArticleCandidate
from src.fetch import canonical_article_url
from src.parse_dates import in_date_range, parse_published
from src.regions import resolve_regions

logger = logging.getLogger(__name__)

DEFAULT_QUERY = "AI impact on labor market employment jobs workers"
MAX_CANDIDATES = 120


def timelimit_for_range(date_from: date, date_to: date) -> str:
    span = (date_to - date_from).days
    if span <= 1:
        return "d"
    if span <= 7:
        return "w"
    return "m"


def _canonical_url(url: str) -> str:
    return canonical_article_url(url)


def _item_to_candidate(
    item: dict,
    *,
    region: str,
    start: date,
    end: date,
    seen_urls: set[str],
) -> ArticleCandidate | None:
    url = (item.get("url") or item.get("link") or "").strip()
    headline = (item.get("title") or "").strip()
    if not url or not headline:
        return None

    canonical = _canonical_url(url)
    if canonical in seen_urls:
        return None

    published = parse_published(item.get("date"))
    if not in_date_range(published, start, end):
        return None

    seen_urls.add(canonical)
    snippet = (item.get("body") or item.get("excerpt") or "").strip()
    source = (item.get("source") or "").strip()

    return ArticleCandidate(
        headline=headline,
        url=canonical,
        published=published,
        source=source,
        snippet=snippet,
        search_region=region,
        provider="ddgs",
    )


def _search_region(
    query: str,
    region: str,
    timelimit: str,
    max_results: int,
) -> list[dict]:
    return DDGS().news(
        query,
        region=region,
        timelimit=timelimit,
        max_results=max_results,
    )


def _discover_region_batch(
    query: str,
    region: str,
    timelimit: str,
    per_region: int,
    start: date,
    end: date,
) -> list[ArticleCandidate]:
    try:
        raw_results = _search_region(query, region, timelimit, per_region)
    except Exception as exc:
        logger.warning("DDGS failed for region %s: %s", region, exc)
        return []

    seen_local: set[str] = set()
    found: list[ArticleCandidate] = []
    for item in raw_results or []:
        candidate = _item_to_candidate(
            item, region=region, start=start, end=end, seen_urls=seen_local
        )
        if candidate:
            found.append(candidate)
    return found


def discover_ddgs(
    query: str = DEFAULT_QUERY,
    max_candidates: int = MAX_CANDIDATES,
    date_from: date | None = None,
    date_to: date | None = None,
    *,
    global_coverage: bool = True,
    regions: list[str] | None = None,
) -> list[ArticleCandidate]:
    """Search DuckDuckGo News across regions in parallel."""
    region_list = resolve_regions(global_coverage=global_coverage, regions=regions)
    today = date.today()
    start = date_from or (today - timedelta(days=7))
    end = date_to or today
    timelimit = timelimit_for_range(start, end)
    workers = int(os.environ.get("DISCOVER_WORKERS", "8"))

    per_region_cap = int(os.environ.get("DDGS_PER_REGION", "12"))
    per_region = max(
        6, min(per_region_cap, (max_candidates * 2) // max(len(region_list), 1))
    )

    logger.info(
        "DDGS parallel: query=%r regions=%d workers=%d per_region=%d target=%d",
        query,
        len(region_list),
        workers,
        per_region,
        max_candidates,
    )

    candidates: list[ArticleCandidate] = []
    seen_urls: set[str] = set()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _discover_region_batch,
                query,
                region,
                timelimit,
                per_region,
                start,
                end,
            )
            for region in region_list
        ]
        for future in as_completed(futures):
            if len(candidates) >= max_candidates:
                break
            for c in future.result():
                if len(candidates) >= max_candidates:
                    break
                if c.url in seen_urls:
                    continue
                seen_urls.add(c.url)
                candidates.append(c)

    logger.info("DDGS: %d candidates from %d regions", len(candidates), len(region_list))
    return candidates


# Backward-compatible alias
def discover_articles(**kwargs) -> list[ArticleCandidate]:
    from src.discovery_hub import discover_all

    return discover_all(**kwargs)

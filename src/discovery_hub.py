"""Merge discovery from all available sources."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from itertools import zip_longest

from src.article import ArticleCandidate
from src.discover import DEFAULT_QUERY, discover_ddgs
from src.eventregistry_client import discover_eventregistry
from src.feeds import discover_broad_google_news, discover_outlet_feeds
from src.newsapi_client import discover_newsapi
from src.reddit_source import discover_reddit

logger = logging.getLogger(__name__)

def _discovery_cap(requested: int, *, newsapi_only: bool = False) -> int:
    """Max candidates to collect across all sources."""
    if newsapi_only:
        return requested
    default = int(os.environ.get("DISCOVERY_MAX_CANDIDATES", "220"))
    return max(requested, default)


def _newsapi_only_enabled(explicit: bool) -> bool:
    if explicit:
        return True
    return os.environ.get("DISCOVERY_SOURCE", "").strip().lower() == "newsapi"


def _api_only_enabled() -> bool:
    """API-only mode: NewsAPI.org + Event Registry, skipping slow DDGS/RSS/Reddit."""
    return os.environ.get("DISCOVERY_SOURCE", "").strip().lower() in {"api", "apis"}


def _eventregistry_only_enabled() -> bool:
    """Event Registry only — structured global AI news with concepts/countries (ER export style)."""
    return os.environ.get("DISCOVERY_SOURCE", "").strip().lower() == "eventregistry"


def _split_discovery_enabled() -> bool:
    """NewsAPI for Europe / North America; Event Registry for Asia, Africa, LatAm, Middle East."""
    return os.environ.get("DISCOVERY_SOURCE", "").strip().lower() == "split"


def _eventregistry_enabled() -> bool:
    return (
        os.environ.get("ENABLE_EVENTREGISTRY", "1") == "1"
        and bool(os.environ.get("EVENTREGISTRY_API_KEY", "").strip())
    )


def newsapi_available() -> bool:
    """True when NEWS_API_KEY is set and NewsAPI should run for the current DISCOVERY_SOURCE."""
    if not os.environ.get("NEWS_API_KEY", "").strip():
        return False
    src = os.environ.get("DISCOVERY_SOURCE", "hybrid").strip().lower()
    if src in {"hybrid", "split", "api", "apis", "newsapi"}:
        return True
    return os.environ.get("ENABLE_NEWSAPI", "0") == "1"


def _newsapi_enabled(*, split_mode: bool = False) -> bool:
    """NewsAPI runs when a key is present in hybrid/split/api modes (or ENABLE_NEWSAPI=1)."""
    del split_mode  # same policy for all modes
    return newsapi_available()


def _merge_candidates(
    batches: list[list[ArticleCandidate]],
    max_total: int,
) -> list[ArticleCandidate]:
    """Interleave candidates round-robin across sources.

    Taking one article per source per round (instead of draining each source in
    turn) stops any single source — e.g. the dozen Western outlet RSS feeds —
    from monopolizing the pool before the cap is reached, so regional API
    sources still land in the candidate set. Order within ``batches`` sets the
    dedup priority: the first source to yield a URL keeps it.
    """
    merged: list[ArticleCandidate] = []
    seen: set[str] = set()
    for group in zip_longest(*batches):
        for c in group:
            if c is None or c.url in seen:
                continue
            seen.add(c.url)
            merged.append(c)
            if len(merged) >= max_total:
                return merged
    return merged


def _supplement_enabled() -> bool:
    """Layer DDGS/RSS/outlet feeds on top of API discovery (strengthens split/hybrid)."""
    return os.environ.get("DISCOVERY_SUPPLEMENT", "1") == "1"


def _append_supplement_sources(
    results: list[ArticleCandidate],
    *,
    query: str,
    start: date,
    end: date,
    cap: int,
    regions: list[str] | None,
    global_coverage: bool,
) -> list[ArticleCandidate]:
    """Add non-API discovery batches up to cap, preserving existing URLs."""
    if not _supplement_enabled() or len(results) >= cap:
        return results
    seen = {c.url for c in results}
    batches: list[list[ArticleCandidate]] = []
    use_outlets = os.environ.get("ENABLE_OUTLET_FEEDS", "1") == "1"
    use_reddit = os.environ.get("ENABLE_REDDIT", "1") == "1"
    use_broad_rss = os.environ.get("ENABLE_BROAD_NEWS", "1") == "1"

    supplement_fns: list = [
        lambda: discover_ddgs(
            query=query,
            max_candidates=min(40, cap),
            date_from=start,
            date_to=end,
            global_coverage=global_coverage,
            regions=regions,
        ),
    ]
    if use_broad_rss:
        supplement_fns.append(
            lambda: discover_broad_google_news(
                query, date_from=start, date_to=end, max_total=min(30, cap)
            )
        )
    if use_outlets:
        supplement_fns.append(
            lambda: discover_outlet_feeds(
                query, date_from=start, date_to=end, max_total=min(30, cap)
            )
        )
    if use_reddit:
        supplement_fns.append(
            lambda: discover_reddit(
                query=query, date_from=start, date_to=end, max_results=15
            )
        )

    def _run_supplement(fn):
        try:
            return fn()
        except Exception:
            logger.exception("Supplement discovery source failed")
            return []

    with ThreadPoolExecutor(max_workers=len(supplement_fns)) as pool:
        for batch in pool.map(_run_supplement, supplement_fns):
            batches.append(batch)

    for batch in batches:
        if not batch:
            continue
        for c in batch:
            if c.url in seen:
                continue
            seen.add(c.url)
            results.append(c)
            if len(results) >= cap:
                return results
    return results


def _merge_er_first(
    primary: list[ArticleCandidate],
    others: list[list[ArticleCandidate]],
    max_total: int,
) -> list[ArticleCandidate]:
    """Fill the pool from Event Registry first (keeps API relevance order), then other sources."""
    merged: list[ArticleCandidate] = []
    seen: set[str] = set()
    for c in primary:
        if c.url in seen:
            continue
        seen.add(c.url)
        merged.append(c)
        if len(merged) >= max_total:
            return merged
    for batch in others:
        for c in batch:
            if c.url in seen:
                continue
            seen.add(c.url)
            merged.append(c)
            if len(merged) >= max_total:
                return merged
    return merged


def discover_all(
    query: str = DEFAULT_QUERY,
    max_candidates: int = 80,
    date_from: date | None = None,
    date_to: date | None = None,
    *,
    global_coverage: bool = True,
    regions: list[str] | None = None,
    newsapi_only: bool = False,
    newsapi_bucket_keys: list[str] | None = None,
    theme_region_keys: list[str] | None = None,
    skip_newsapi: bool = False,
) -> list[ArticleCandidate]:
    """Run all enabled discovery sources and return deduped candidates."""
    today = date.today()
    start = date_from or (today - timedelta(days=7))
    end = date_to or today

    if _newsapi_only_enabled(newsapi_only) and not skip_newsapi:
        api_key = os.environ.get("NEWS_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "NewsAPI credentials are required for NewsAPI-only discovery. "
                "Configure them in .env (see README)."
            )
        cap = _discovery_cap(max_candidates, newsapi_only=True)
        results = discover_newsapi(
            query,
            date_from=start,
            date_to=end,
            max_results=cap,
            bucket_keys=newsapi_bucket_keys,
        )
        if not results and os.environ.get("DISCOVERY_FALLBACK_DDGS", "1") == "1":
            logger.warning(
                "NewsAPI returned 0 articles; falling back to DuckDuckGo regional search"
            )
            results = discover_ddgs(
                query=query,
                max_candidates=cap,
                date_from=start,
                date_to=end,
                global_coverage=False,
                regions=regions,
            )
        logger.info("NewsAPI-only discovery: %d articles", len(results))
        return results

    if _eventregistry_only_enabled():
        if not _eventregistry_enabled():
            raise RuntimeError(
                "Event Registry credentials are required for eventregistry discovery. "
                "Configure them in .env (see README)."
            )
        cap = _discovery_cap(max_candidates, newsapi_only=True)
        results = discover_eventregistry(
            query,
            date_from=start,
            date_to=end,
            max_results=cap,
            bucket_keys=newsapi_bucket_keys,
            theme_region_keys=theme_region_keys,
        )
        logger.info(
            "Event Registry-only discovery: %d articles (mode=%s)",
            len(results),
            os.environ.get("EVENTREGISTRY_QUERY_MODE", "ai_export"),
        )
        return results

    if _split_discovery_enabled():
        from dataclasses import replace

        from src.thematic_regions import split_discovery_plan

        plan = split_discovery_plan(theme_region_keys or [])
        if skip_newsapi:
            plan = replace(plan, use_newsapi=False, newsapi_bucket_keys=None)
            if not plan.use_eventregistry:
                plan = replace(
                    plan,
                    use_eventregistry=True,
                    eventregistry_theme_keys=None,
                )
        cap = _discovery_cap(max_candidates, newsapi_only=True)
        er_batch: list[ArticleCandidate] = []
        other_batches: list[list[ArticleCandidate]] = []

        if plan.use_eventregistry:
            if not _eventregistry_enabled():
                raise RuntimeError(
                    "Event Registry credentials are required for split discovery "
                    "(Asia, Africa, Latin America, Middle East, or Global)."
                )
            er_themes = (
                list(plan.eventregistry_theme_keys)
                if plan.eventregistry_theme_keys
                else None
            )
            er_batch = discover_eventregistry(
                query,
                date_from=start,
                date_to=end,
                max_results=cap,
                bucket_keys=newsapi_bucket_keys,
                theme_region_keys=er_themes,
            )

        if plan.use_newsapi:
            if not _newsapi_enabled(split_mode=True):
                raise RuntimeError(
                    "NewsAPI credentials are required for split discovery "
                    "(Europe or North America)."
                )
            buckets = (
                list(plan.newsapi_bucket_keys)
                if plan.newsapi_bucket_keys
                else None
            )
            other_batches.append(
                discover_newsapi(
                    query,
                    date_from=start,
                    date_to=end,
                    max_results=cap,
                    bucket_keys=buckets,
                )
            )

        if not er_batch and not other_batches:
            raise RuntimeError(
                "DISCOVERY_SOURCE=split: no provider matched the selected regions. "
                "Use Europe or North America (NewsAPI) and/or Asia, Africa, Latin America, "
                "Middle East (Event Registry)."
            )

        if er_batch:
            results = _merge_er_first(er_batch, other_batches, cap)
        else:
            results = _merge_candidates(other_batches, cap)

        results = _append_supplement_sources(
            results,
            query=query,
            start=start,
            end=end,
            cap=cap,
            regions=regions,
            global_coverage=False,
        )

        if not results and os.environ.get("DISCOVERY_FALLBACK_DDGS", "1") == "1":
            logger.warning(
                "Split API discovery returned 0 articles; falling back to DuckDuckGo"
            )
            results = discover_ddgs(
                query=query,
                max_candidates=cap,
                date_from=start,
                date_to=end,
                global_coverage=False,
                regions=regions,
            )
        logger.info(
            "Split discovery: %d articles (ER=%s NewsAPI=%s themes=%s)",
            len(results),
            plan.use_eventregistry,
            plan.use_newsapi,
            list(theme_region_keys or []),
        )
        return results

    if _api_only_enabled():
        cap = _discovery_cap(max_candidates, newsapi_only=True)
        er_batch: list[ArticleCandidate] = []
        other_batches: list[list[ArticleCandidate]] = []
        if _eventregistry_enabled():
            er_batch = discover_eventregistry(
                query,
                date_from=start,
                date_to=end,
                max_results=cap,
                bucket_keys=newsapi_bucket_keys,
                theme_region_keys=theme_region_keys,
            )
        if _newsapi_enabled() and not skip_newsapi:
            other_batches.append(
                discover_newsapi(
                    query,
                    date_from=start,
                    date_to=end,
                    max_results=cap,
                    bucket_keys=newsapi_bucket_keys,
                )
            )
        if not er_batch and not other_batches:
            raise RuntimeError(
                "API discovery needs at least one configured provider "
                "(NewsAPI or Event Registry) in .env."
            )
        if er_batch:
            results = _merge_er_first(er_batch, other_batches, cap)
        else:
            results = _merge_candidates(other_batches, cap)
        results = _append_supplement_sources(
            results,
            query=query,
            start=start,
            end=end,
            cap=cap,
            regions=regions,
            global_coverage=False,
        )
        if not results and os.environ.get("DISCOVERY_FALLBACK_DDGS", "1") == "1":
            logger.warning(
                "News APIs returned 0 articles; falling back to DuckDuckGo regional search"
            )
            results = discover_ddgs(
                query=query,
                max_candidates=cap,
                date_from=start,
                date_to=end,
                global_coverage=False,
                regions=regions,
            )
        logger.info(
            "API-only discovery: %d articles from providers %s",
            len(results),
            sorted({c.provider for c in results}),
        )
        return results

    cap = _discovery_cap(max_candidates)

    use_outlets = os.environ.get("ENABLE_OUTLET_FEEDS", "1") == "1"
    use_reddit = os.environ.get("ENABLE_REDDIT", "1") == "1"
    use_broad_rss = os.environ.get("ENABLE_BROAD_NEWS", "1") == "1"
    use_newsapi = _newsapi_enabled() and not skip_newsapi

    # Source order sets round-robin/dedup priority in _merge_candidates. The most
    # relevant + globally diverse source (Event Registry concept search) goes first,
    # then the regional, on-topic API sources (NewsAPI buckets, DDGS regional search),
    # so their results aren't crowded out of the capped pool by the many Western
    # outlet feeds. Each source already parallelizes internally, and the sources run
    # concurrently below so total discovery time is the slowest single source, not
    # the sum of all of them.
    sources: list = []

    if _eventregistry_enabled():
        sources.append(
            lambda: discover_eventregistry(
                query,
                date_from=start,
                date_to=end,
                max_results=min(50, cap),
                bucket_keys=newsapi_bucket_keys,
                theme_region_keys=theme_region_keys,
            )
        )
    if use_newsapi:
        sources.append(
            lambda: discover_newsapi(
                query,
                date_from=start,
                date_to=end,
                max_results=min(50, cap),
                bucket_keys=newsapi_bucket_keys,
            )
        )
    sources.append(
        lambda: discover_ddgs(
            query=query,
            max_candidates=min(80, cap),
            date_from=start,
            date_to=end,
            global_coverage=global_coverage,
            regions=regions,
        )
    )
    if use_broad_rss:
        sources.append(
            lambda: discover_broad_google_news(
                query, date_from=start, date_to=end, max_total=min(60, cap)
            )
        )
    if use_outlets:
        sources.append(
            lambda: discover_outlet_feeds(
                query, date_from=start, date_to=end, max_total=min(60, cap)
            )
        )
    if use_reddit:
        sources.append(
            lambda: discover_reddit(
                query=query, date_from=start, date_to=end, max_results=25
            )
        )

    def _run(idx_fn):
        idx, fn = idx_fn
        try:
            return idx, fn()
        except Exception:  # one failing source must not abort discovery
            logger.exception("Discovery source %d failed", idx)
            return idx, []

    results: dict[int, list[ArticleCandidate]] = {}
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        for idx, batch in pool.map(_run, list(enumerate(sources))):
            results[idx] = batch

    # Preserve original source order so merge dedup keeps the same priority.
    batches = [results[i] for i in range(len(sources))]
    merged = _merge_candidates(batches, cap)
    providers = {c.provider for c in merged}
    logger.info(
        "Discovery hub: %d articles (cap %d) from providers %s",
        len(merged),
        cap,
        sorted(providers),
    )
    return merged

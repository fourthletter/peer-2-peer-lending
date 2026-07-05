"""Labor-impact visualization — independent of digest ranking and summarization."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta

from src.config import DigestConfig
from src.discover import DEFAULT_QUERY
from src.discovery_hub import discover_viz_supplements, newsapi_available
from src.eventregistry_client import (
    discover_eventregistry,
    discover_eventregistry_viz,
    discover_eventregistry_viz_themes,
    fetch_viz_year_candidates,
)
from src.labor_impact_parse import VIZ_MIN_DATE, build_impact_dataset, empty_impact_viz
from src.newsapi_client import discover_newsapi
from src.storage import normalize_url
from src.thematic_regions import (
    EVENTREGISTRY_DISCOVERY_THEMES,
    classify_thematic_region,
    format_filter_summary,
    normalize_region_selection,
    viz_focus_region_ids,
    viz_newsapi_bucket_keys,
)
from src.viz_cache import load_year_candidates, save_year_candidates

logger = logging.getLogger(__name__)


@dataclass
class ImpactVizResult:
    records: list[dict]
    viz: dict
    discovered: int
    filter_summary: str = ""


def _viz_live_max() -> int:
    raw = os.environ.get("VIZ_DISCOVER_MAX_RESULTS", "150").strip()
    if raw.isdigit():
        return min(max(int(raw), 20), 200)
    return 150


def _viz_per_year() -> int:
    raw = os.environ.get("EVENTREGISTRY_VIZ_PER_YEAR", "32").strip()
    if raw.isdigit():
        return min(max(int(raw), 6), 100)
    return 32


def _viz_newsapi_max(live_max: int) -> int:
    raw = os.environ.get("VIZ_NEWSAPI_MAX", "80").strip()
    if raw.isdigit():
        return min(max(int(raw), 10), live_max)
    return min(80, live_max)


def _viz_er_broad_enabled() -> bool:
    return os.environ.get("VIZ_ER_BROAD", "1") == "1"


def _viz_theme_region_keys(geographic_regions: tuple[str, ...]) -> list[str]:
    """Focus themes for viz discovery — user selection or Africa / LatAm / MENA default."""
    themes = [
        t
        for t in normalize_region_selection(list(geographic_regions))
        if t in EVENTREGISTRY_DISCOVERY_THEMES
    ]
    if themes:
        return themes
    return list(viz_focus_region_ids())


def _interleave_batches(batches: list[list]) -> list:
    """Round-robin merge so regional batches are not drowned out by global pulls."""
    from itertools import zip_longest

    merged: list = []
    seen: set[str] = set()
    for group in zip_longest(*batches):
        for c in group:
            if c is None:
                continue
            key = normalize_url(c.url)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(c)
    return merged


def _merge_candidates_unique(
    batches: list[list],
    seen: set[str],
) -> list:
    merged = []
    for batch in batches:
        for c in batch:
            key = normalize_url(c.url)
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(c)
    return merged


def _collect_years_cached(
    viz_from: date,
    viz_to: date,
    *,
    theme_region_keys: list[str] | None,
    force_refresh: bool,
) -> list:
    """Load or fetch one ER labor batch per calendar year."""
    if os.environ.get("VIZ_YEAR_CACHE", "1") != "1":
        return []

    today_year = date.today().year
    per_year = _viz_per_year()
    batches: list[list] = []

    for year in range(viz_from.year, viz_to.year + 1):
        refresh_year = force_refresh or year >= today_year
        cached = None if refresh_year else load_year_candidates(year)
        if cached is not None:
            batches.append(cached)
            logger.info("Viz year cache hit: %d (%d articles)", year, len(cached))
            continue

        batch = fetch_viz_year_candidates(
            year,
            date_from=viz_from,
            date_to=viz_to,
            per_year=per_year,
            theme_region_keys=theme_region_keys,
        )
        if batch:
            save_year_candidates(year, batch)
            logger.info("Viz year cache saved: %d (%d articles)", year, len(batch))
        batches.append(batch or [])

    seen: set[str] = set()
    return _merge_candidates_unique(batches, seen)


def collect_viz_candidates(config: DigestConfig) -> list:
    """Discover articles for charts — streamlined ER pulls + per-year disk cache."""
    viz_from = max(config.date_from, VIZ_MIN_DATE)
    viz_to = config.date_to
    theme_keys = _viz_theme_region_keys(config.geographic_regions)
    force_refresh = os.environ.get("VIZ_CACHE_REFRESH", "0") == "1"
    live_max = _viz_live_max()
    batches: list[list] = []

    span_days = (viz_to - viz_from).days
    recent_from = max(viz_from, viz_to - timedelta(days=365))
    query = config.query or DEFAULT_QUERY
    er_from = recent_from if span_days >= 400 else viz_from

    # Priority: per-theme regional Event Registry (Africa, LatAm, MENA)
    if os.environ.get("EVENTREGISTRY_API_KEY", "").strip():
        batches.append(
            discover_eventregistry_viz_themes(
                er_from,
                viz_to,
                theme_keys,
            )
        )

    if span_days >= 400:
        batches.append(
            _collect_years_cached(
                viz_from,
                viz_to,
                theme_region_keys=theme_keys,
                force_refresh=force_refresh,
            )
        )
        batches.append(
            discover_eventregistry_viz(
                recent_from,
                viz_to,
                max_results=live_max,
                theme_region_keys=theme_keys,
            )
        )
    else:
        batches.append(
            discover_eventregistry_viz(
                viz_from,
                viz_to,
                max_results=live_max,
                theme_region_keys=theme_keys,
            )
        )

    if _viz_er_broad_enabled() and os.environ.get("EVENTREGISTRY_API_KEY", "").strip():
        batches.append(
            discover_eventregistry(
                query,
                date_from=er_from,
                date_to=viz_to,
                max_results=live_max,
                theme_region_keys=theme_keys,
            )
        )

    if newsapi_available():
        batches.append(
            discover_newsapi(
                query,
                date_from=viz_from,
                date_to=viz_to,
                max_results=_viz_newsapi_max(live_max),
                bucket_keys=viz_newsapi_bucket_keys(),
            )
        )

    batches.append(
        discover_viz_supplements(
            query=query,
            date_from=viz_from,
            date_to=viz_to,
            theme_region_keys=theme_keys,
            global_coverage=False,
        )
    )

    candidates = _interleave_batches(batches)
    for c in candidates:
        c.thematic_region = classify_thematic_region(c)

    logger.info(
        "Viz discovery (streamlined): %d candidates, %s – %s",
        len(candidates),
        viz_from.isoformat(),
        viz_to.isoformat(),
    )
    return candidates


def build_labor_impact_viz(
    config: DigestConfig,
    *,
    digest_urls: set[str] | None = None,
) -> ImpactVizResult:
    """Build parsed records and chart aggregates for the labor-impact panel."""
    candidates = collect_viz_candidates(config)
    viz_from = max(config.date_from, VIZ_MIN_DATE)
    viz_to = config.date_to

    max_records = int(os.environ.get("IMPACT_VIZ_MAX_RECORDS", "400"))
    try:
        records, viz = build_impact_dataset(
            candidates,
            date_from=viz_from,
            date_to=viz_to,
            digest_urls=digest_urls or set(),
            max_records=max_records,
        )
    except Exception:
        logger.exception("Labor impact visualization failed")
        records = []
        viz = empty_impact_viz(year_label=viz_from.isoformat() + " – " + viz_to.isoformat())

    logger.info(
        "Labor impact viz: %d parsed from %d discovered",
        len(records),
        len(candidates),
    )
    return ImpactVizResult(
        records=records,
        viz=viz,
        discovered=len(candidates),
        filter_summary=format_filter_summary(
            theme_ids=list(config.geographic_regions),
            extra_keywords=config.extra_keywords,
        ),
    )

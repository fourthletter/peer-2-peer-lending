"""Geographic diversity when selecting top-ranked articles."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from src.coverage import infer_publisher_country
from src.thematic_regions import (
    AFRICA_COUNTRIES,
    ASIA_COUNTRIES,
    DEFAULT_FOCUS_REGIONS,
    EUROPE_COUNTRIES,
    LATIN_AMERICA_COUNTRIES,
    MIDDLE_EAST_COUNTRIES,
    NORTH_AMERICA_COUNTRIES,
    default_geographic_regions,
    resolve_pick_order,
)

if TYPE_CHECKING:
    from src.rank import RankedArticle

LEGACY_PICK_ORDER = ("europe", "global_majority", "north_america", "unknown")


def geo_diversity_enabled() -> bool:
    return os.environ.get("RANK_GEO_DIVERSITY", "1") == "1"


def max_per_geo_bucket() -> int:
    return max(1, int(os.environ.get("RANK_MAX_PER_GEO", "1")))


def geographic_bucket(article: RankedArticle) -> str:
    """Map article to a geographic bucket for diversity selection."""
    search = (article.search_region or "").lower()
    if search.startswith("newsapi:asia"):
        return "asia"
    if search.startswith("newsapi:africa"):
        return "africa"
    if search.startswith("newsapi:latin_america"):
        return "latin_america"
    if search.startswith("newsapi:middle_east"):
        return "middle_east"
    if search.startswith("newsapi:eu"):
        return "europe"
    if search.startswith("newsapi:global_majority"):
        return _bucket_from_country(article)

    country = (article.publisher_country or "").strip()
    if not country:
        country = infer_publisher_country(source=article.source, url=article.url)

    return _bucket_from_country_value(country)


def _bucket_from_country(article: RankedArticle) -> str:
    country = (article.publisher_country or "").strip()
    if not country:
        country = infer_publisher_country(source=article.source, url=article.url)
    return _bucket_from_country_value(country)


def _bucket_from_country_value(country: str) -> str:
    if not country:
        return "unknown"
    if country in NORTH_AMERICA_COUNTRIES:
        return "north_america"
    if country in EUROPE_COUNTRIES:
        return "europe"
    if country in ASIA_COUNTRIES:
        return "asia"
    if country in AFRICA_COUNTRIES:
        return "africa"
    if country in LATIN_AMERICA_COUNTRIES:
        return "latin_america"
    if country in MIDDLE_EAST_COUNTRIES:
        return "middle_east"
    return "global_majority"


def diversify_ranked(
    scored: list[RankedArticle],
    top_n: int,
    *,
    pick_order: tuple[str, ...] | None = None,
) -> list[RankedArticle]:
    """
    Select top_n articles with round-robin across geographic buckets.
    Input must be sorted by relevance (score) descending.
    """
    if not scored or top_n <= 0:
        return []

    order = pick_order or resolve_pick_order(default_geographic_regions())
    max_per = max_per_geo_bucket()
    by_bucket: dict[str, list[RankedArticle]] = {b: [] for b in order}
    for legacy in LEGACY_PICK_ORDER:
        if legacy not in by_bucket:
            by_bucket[legacy] = []
    for article in scored:
        bucket = geographic_bucket(article)
        if bucket not in by_bucket:
            by_bucket[bucket] = []
        by_bucket[bucket].append(article)

    selected: list[RankedArticle] = []
    picked_ids: set[int] = set()
    bucket_counts: dict[str, int] = {b: 0 for b in by_bucket}

    while len(selected) < top_n:
        progressed = False
        for bucket in order:
            if len(selected) >= top_n:
                break
            if bucket_counts.get(bucket, 0) >= max_per:
                continue
            pool = by_bucket.get(bucket, [])
            while pool and id(pool[0]) in picked_ids:
                pool.pop(0)
            if not pool:
                continue
            article = pool.pop(0)
            selected.append(article)
            picked_ids.add(id(article))
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
            progressed = True
        if not progressed:
            break

    if len(selected) < top_n:
        for article in scored:
            if len(selected) >= top_n:
                break
            if id(article) not in picked_ids:
                selected.append(article)
                picked_ids.add(id(article))

    return selected

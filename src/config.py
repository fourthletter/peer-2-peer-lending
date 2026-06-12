"""Configuration for digest runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.discover import DEFAULT_QUERY

MIN_ARTICLE_COUNT = 1
MAX_ARTICLE_COUNT = 20
DEFAULT_ARTICLE_COUNT = 5
DEFAULT_LOOKBACK_DAYS = 7


@dataclass
class DigestConfig:
    date_from: date
    date_to: date
    article_count: int = DEFAULT_ARTICLE_COUNT
    query: str = DEFAULT_QUERY
    skip_dedup: bool = True
    global_coverage: bool = True
    newsapi_only: bool = False
    extra_keywords: str = ""
    geographic_regions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.date_from > self.date_to:
            raise ValueError("Start date must be on or before end date.")
        if not MIN_ARTICLE_COUNT <= self.article_count <= MAX_ARTICLE_COUNT:
            raise ValueError(
                f"Article count must be between {MIN_ARTICLE_COUNT} and "
                f"{MAX_ARTICLE_COUNT}."
            )
        from src.thematic_regions import (
            build_config_query,
            default_geographic_regions,
            normalize_region_selection,
        )

        normalized = normalize_region_selection(list(self.geographic_regions))
        self.geographic_regions = tuple(normalized) if normalized else default_geographic_regions()
        if self.extra_keywords.strip():
            self.query = build_config_query(self.extra_keywords, base=self.query)

    @classmethod
    def default_weekly(cls) -> DigestConfig:
        from src.thematic_regions import default_geographic_regions

        today = date.today()
        return cls(
            date_from=today - timedelta(days=DEFAULT_LOOKBACK_DAYS),
            date_to=today,
            article_count=DEFAULT_ARTICLE_COUNT,
            geographic_regions=default_geographic_regions(),
        )

    @property
    def discover_max_results(self) -> int:
        """How many articles to collect from discovery."""
        import os as _os

        src = _os.environ.get("DISCOVERY_SOURCE", "").strip().lower()
        cap_env = int(_os.environ.get("DISCOVERY_MAX_CANDIDATES", "220") or "220")
        if src in {"eventregistry", "api", "apis", "newsapi", "split", "hybrid"}:
            return min(max(self.article_count * 15, 60), cap_env)
        if self.newsapi_only:
            return min(max(self.article_count * 15, 60), cap_env)
        base = max(self.article_count * 8, 50)
        if self.global_coverage:
            return min(max(base, 100), cap_env)
        return min(base, cap_env)

    @property
    def max_to_rank(self) -> int:
        """How many candidates to score before picking top N."""
        import os

        override = os.environ.get("MAX_TO_RANK", "").strip()
        if override.isdigit() and int(override) > 0:
            return int(override)
        # Cap at ~12 to keep the (LLM) ranking prompt small and fast; this is
        # still ~2x the requested article count, leaving room to pick the best.
        return min(max(self.article_count * 2, 10), 12)

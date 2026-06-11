"""Shared article candidate model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ArticleCandidate:
    headline: str
    url: str
    published: datetime | None
    source: str
    snippet: str
    search_region: str = ""
    thematic_region: str = ""
    provider: str = "ddgs"
    # Event Registry annotations (concepts / orgs / country from article concepts).
    concepts: tuple[str, ...] = ()
    companies: tuple[str, ...] = ()
    location_country: str = ""
    # Event Registry articlesSortBy=rel score (higher = more on-topic).
    relevance_score: float = 0.0

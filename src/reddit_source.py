"""Reddit discussion discovery via DDGS (no OAuth required)."""

from __future__ import annotations

import logging
from datetime import date

from ddgs import DDGS

from src.article import ArticleCandidate
from src.discover import DEFAULT_QUERY, _item_to_candidate, timelimit_for_range

logger = logging.getLogger(__name__)

REDDIT_SCOPE = (
    "site:reddit.com (r/economics OR r/jobs OR r/artificial OR r/MachineLearning "
    "OR r/labor OR r/work OR r/careerguidance OR r/futurology)"
)


def discover_reddit(
    query: str = DEFAULT_QUERY,
    *,
    date_from: date,
    date_to: date,
    max_results: int = 25,
) -> list[ArticleCandidate]:
    """Find Reddit threads about AI and labor via DuckDuckGo."""
    timelimit = timelimit_for_range(date_from, date_to)
    full_query = f"{query} {REDDIT_SCOPE}"

    seen: set[str] = set()
    candidates: list[ArticleCandidate] = []
    ddgs = DDGS()

    for method_name, search_fn in (("news", ddgs.news), ("text", ddgs.text)):
        try:
            raw = search_fn(
                full_query, region="wt-wt", timelimit=timelimit, max_results=max_results
            )
        except Exception as exc:
            logger.warning("Reddit DDGS %s search failed: %s", method_name, exc)
            continue
        for item in raw or []:
            c = _item_to_candidate(
                item, region="reddit", start=date_from, end=date_to, seen_urls=seen
            )
            if c:
                c.provider = "reddit"
                c.source = c.source or "Reddit"
                candidates.append(c)
            if len(candidates) >= max_results:
                break
        if len(candidates) >= max_results:
            break

    logger.info("Reddit: %d candidates", len(candidates))
    return candidates[:max_results]

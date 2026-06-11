"""Normalize search queries for NewsAPI boolean syntax."""

from __future__ import annotations

import re

# NewsAPI matches poorly on long natural-language strings; boolean queries work better.
DEFAULT_NEWSAPI_QUERY = (
    "(AI OR artificial intelligence) AND "
    "(jobs OR employment OR workers OR labor OR workforce OR automation)"
)

_BOOLEAN_HINT = re.compile(r'[&|()]|"\s*OR\s*"|"\s*AND\s*"', re.I)


def _looks_boolean(query: str) -> bool:
    return bool(_BOOLEAN_HINT.search(query))


def to_newsapi_query(query: str) -> str:
    """Convert a natural-language digest query into a NewsAPI-friendly boolean query."""
    text = (query or "").strip()
    if not text:
        return DEFAULT_NEWSAPI_QUERY
    if _looks_boolean(text):
        return text

    lower = text.lower()
    labor_terms = (
        "labor",
        "labour",
        "employment",
        "jobs",
        "workers",
        "workforce",
        "automation",
    )
    if any(term in lower for term in labor_terms):
        return DEFAULT_NEWSAPI_QUERY

    # Short user keyword phrases: keep as-is but add AI context when missing.
    if "ai" not in lower and "artificial intelligence" not in lower:
        return f'(AI OR artificial intelligence) AND ({text})'
    return text


def query_fallbacks(query: str) -> list[str]:
    """Ordered queries to try when the primary NewsAPI search returns nothing."""
    primary = to_newsapi_query(query)
    fallbacks = [
        primary,
        "AI AND (jobs OR employment OR workers OR labor OR workforce)",
        "AI jobs OR employment automation",
        "artificial intelligence jobs OR workers OR employment",
    ]
    raw = (query or "").strip()
    if raw and raw not in fallbacks:
        fallbacks.insert(1, raw)

    seen: set[str] = set()
    ordered: list[str] = []
    for q in fallbacks:
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            ordered.append(q)
    return ordered

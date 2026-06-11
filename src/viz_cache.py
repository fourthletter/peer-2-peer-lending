"""Disk cache for labor-impact viz (session cookies are too small)."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path

from src.article import ArticleCandidate

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent


def viz_cache_dir() -> Path:
    raw = os.environ.get("VIZ_CACHE_DIR", "").strip()
    if raw:
        return Path(raw)
    return ROOT / ".viz_cache"


def payload_file() -> Path:
    return viz_cache_dir() / "payload.json"


def year_cache_dir() -> Path:
    return viz_cache_dir() / "years"


def _candidate_to_dict(c: ArticleCandidate) -> dict:
    published = None
    if c.published:
        published = (
            c.published.isoformat()
            if isinstance(c.published, datetime)
            else str(c.published)
        )
    return {
        "headline": c.headline,
        "url": c.url,
        "published": published,
        "source": c.source,
        "snippet": c.snippet,
        "search_region": c.search_region,
        "thematic_region": c.thematic_region,
        "provider": c.provider,
        "concepts": list(c.concepts),
        "companies": list(c.companies),
        "location_country": c.location_country,
        "relevance_score": c.relevance_score,
    }


def _candidate_from_dict(raw: dict) -> ArticleCandidate:
    published = None
    if raw.get("published"):
        try:
            published = datetime.fromisoformat(raw["published"].replace("Z", "+00:00"))
        except ValueError:
            published = None
    return ArticleCandidate(
        headline=raw.get("headline") or "",
        url=raw.get("url") or "",
        published=published,
        source=raw.get("source") or "",
        snippet=raw.get("snippet") or "",
        search_region=raw.get("search_region") or "",
        thematic_region=raw.get("thematic_region") or "",
        provider=raw.get("provider") or "eventregistry",
        concepts=tuple(raw.get("concepts") or ()),
        companies=tuple(raw.get("companies") or ()),
        location_country=raw.get("location_country") or "",
        relevance_score=float(raw.get("relevance_score") or 0),
    )


def year_cache_path(year: int) -> Path:
    return year_cache_dir() / f"{year}.json"


def load_year_candidates(year: int) -> list[ArticleCandidate] | None:
    path = year_cache_path(year)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [_candidate_from_dict(item) for item in raw.get("candidates") or []]
    except (OSError, json.JSONDecodeError, TypeError):
        logger.warning("Could not read year cache %s", path)
        return None


def save_year_candidates(year: int, candidates: list[ArticleCandidate]) -> None:
    year_cache_dir().mkdir(parents=True, exist_ok=True)
    payload = {
        "year": year,
        "cached_at": date.today().isoformat(),
        "candidates": [_candidate_to_dict(c) for c in candidates],
    }
    year_cache_path(year).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def load_payload_cache() -> dict | None:
    path = payload_file()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read viz payload cache")
        return None


def save_payload_cache(payload: dict) -> None:
    cache_dir = viz_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload_file().write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

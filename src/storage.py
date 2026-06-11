"""Persist sent article URLs for deduplication."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SENT_URLS_PATH = ROOT / "data" / "sent_urls.json"


def normalize_url(url: str) -> str:
    """Normalize URL for comparison (strip fragment, trailing slash)."""
    parsed = urlparse(url.strip())
    path = parsed.path.rstrip("/") or "/"
    normalized = urlunparse(
        (parsed.scheme, parsed.netloc.lower(), path, parsed.params, parsed.query, "")
    )
    return normalized


def load_sent_urls() -> set[str]:
    """Load set of previously sent normalized URLs."""
    if not SENT_URLS_PATH.exists():
        return set()
    try:
        data = json.loads(SENT_URLS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read sent URLs: %s", exc)
        return set()

    urls: set[str] = set()
    for item in data:
        if isinstance(item, str):
            urls.add(normalize_url(item))
        elif isinstance(item, dict) and "url" in item:
            urls.add(normalize_url(item["url"]))
    return urls


def save_sent_urls(existing: set[str], new_urls: list[str]) -> None:
    """Append newly sent URLs to the history file."""
    SENT_URLS_PATH.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    if SENT_URLS_PATH.exists():
        try:
            raw = json.loads(SENT_URLS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                records = [r for r in raw if isinstance(r, dict)]
        except (json.JSONDecodeError, OSError):
            records = []

    now = datetime.now(timezone.utc).isoformat()
    known = {normalize_url(r.get("url", "")) for r in records}

    for url in new_urls:
        norm = normalize_url(url)
        if norm not in known and norm not in existing:
            records.append({"url": url, "sent_at": now})
            known.add(norm)

    SENT_URLS_PATH.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    logger.info("Saved %d total sent URL records", len(records))

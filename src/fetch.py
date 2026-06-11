"""Fetch and extract article text from URLs."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qs, urlparse

import requests
from trafilatura import extract, fetch_url

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15
MAX_TEXT_CHARS = 6000


def _decode_google_news(url: str) -> str | None:
    if "news.google.com" not in url:
        return None
    try:
        from googlenewsdecoder import gnewsdecoder

        result = gnewsdecoder(url)
        if result.get("status") and result.get("decoded_url"):
            return result["decoded_url"]
    except Exception as exc:
        logger.warning("Google News decode failed for %s: %s", url, exc)
    return None


def is_wrapped_news_url(url: str) -> bool:
    """True if URL is a Google News wrapper rather than the publisher link."""
    if not url:
        return False
    lower = url.lower()
    if "news.google.com" in lower:
        return True
    if "google.com/url" in lower:
        return True
    return False


def canonical_article_url(url: str) -> str:
    """Resolve Google News wrappers and redirects to the publisher article URL."""
    raw = (url or "").strip()
    if not raw:
        return raw

    if "google.com/url" in raw.lower():
        parsed = urlparse(raw)
        query = parse_qs(parsed.query)
        target = query.get("url", [None])[0] or query.get("q", [None])[0]
        if target:
            return canonical_article_url(target)

    if "news.google.com" in raw.lower():
        decoded = _decode_google_news(raw)
        if decoded:
            return decoded
        return resolve_url(raw)

    return raw


def resolve_url(url: str) -> str:
    if is_wrapped_news_url(url):
        return canonical_article_url(url)

    try:
        resp = requests.head(
            url, allow_redirects=True, timeout=REQUEST_TIMEOUT, headers=_headers()
        )
        return resp.url or url
    except requests.RequestException:
        try:
            resp = requests.get(
                url, allow_redirects=True, timeout=REQUEST_TIMEOUT, headers=_headers()
            )
            return resp.url or url
        except requests.RequestException:
            return url


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (compatible; NewsAgent/1.0)"
    }


def fetch_article_text(url: str) -> str:
    try:
        downloaded = fetch_url(url)
        if not downloaded:
            return ""
        text = extract(downloaded)
        return (text or "").strip()
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return ""


def enrich_candidate(url: str, snippet: str, *, fetch_full: bool = True) -> str:
    """Fetch full article text, or use snippet only when fetch_full=False."""
    if not fetch_full:
        return (snippet or "")[:MAX_TEXT_CHARS]
    text = fetch_article_text(url)
    if not text:
        text = snippet
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
    return text


def enrich_candidates_parallel(
    candidates: list[dict],
    *,
    fetch_full: bool = True,
) -> list[dict]:
    """Enrich multiple candidates concurrently."""
    if not candidates:
        return []

    workers = int(os.environ.get("FETCH_WORKERS", "6"))
    results: list[dict | None] = [None] * len(candidates)

    def _one(idx: int, item: dict) -> tuple[int, dict]:
        article_url = canonical_article_url(item["url"])
        text = enrich_candidate(
            article_url,
            item.get("snippet") or "",
            fetch_full=fetch_full,
        )
        return idx, {**item, "url": article_url, "text": text}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, i, c) for i, c in enumerate(candidates)]
        for future in as_completed(futures):
            idx, enriched = future.result()
            results[idx] = enriched

    return [r for r in results if r is not None]

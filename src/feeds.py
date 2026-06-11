"""News discovery via Google News RSS (broad and outlet-scoped)."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from urllib.parse import quote_plus

import feedparser
import requests

from src.article import ArticleCandidate
from src.fetch import _headers
from src.parse_dates import in_date_range, parse_published
from src.text_utils import strip_html

logger = logging.getLogger(__name__)

GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
)

# Major outlets (site-scoped searches run in parallel)
OUTLET_SEARCHES: list[tuple[str, str]] = [
    ("Reuters", "site:reuters.com"),
    ("Associated Press", "site:apnews.com"),
    ("BBC", "site:bbc.com"),
    ("The Guardian", "site:theguardian.com"),
    ("NPR", "site:npr.org"),
    ("Financial Times", "site:ft.com"),
    ("Bloomberg", "site:bloomberg.com"),
    ("Wall Street Journal", "site:wsj.com"),
    ("New York Times", "site:nytimes.com"),
    ("Washington Post", "site:washingtonpost.com"),
    ("CNBC", "site:cnbc.com"),
    ("Al Jazeera", "site:aljazeera.com"),
    ("Economist", "site:economist.com"),
    ("TechCrunch", "site:techcrunch.com"),
    ("Wired", "site:wired.com"),
    ("MIT Technology Review", "site:technologyreview.com"),
    ("Harvard Business Review", "site:hbr.org"),
    ("ILO", "site:ilo.org"),
    ("World Economic Forum", "site:weforum.org"),
    ("Rest of World", "site:restofworld.org"),
]


def _fetch_feed(url: str) -> bytes | None:
    try:
        resp = requests.get(url, timeout=12, headers=_headers())
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as exc:
        logger.warning("RSS fetch failed %s: %s", url, exc)
        return None


def _parse_feed_entries(
    content: bytes,
    *,
    source_label: str,
    provider: str,
    start: date,
    end: date,
    max_items: int,
    seen: set[str] | None = None,
) -> list[ArticleCandidate]:
    feed = feedparser.parse(content)
    results: list[ArticleCandidate] = []
    local_seen = seen if seen is not None else set()

    for entry in feed.entries:
        if len(results) >= max_items:
            break
        # Keep the raw link here; resolving Google News wrappers makes a network
        # call per entry. We defer that to the enrichment step, which only runs
        # on the final ranked winners and does so in parallel.
        link = (entry.get("link") or "").strip()
        title = (entry.get("title") or "").strip()
        if not link or not title or link in local_seen:
            continue
        published = parse_published(entry.get("published") or entry.get("updated"))
        if not in_date_range(published, start, end):
            continue
        local_seen.add(link)
        summary = strip_html(entry.get("summary") or entry.get("description") or "")
        results.append(
            ArticleCandidate(
                headline=title,
                url=link,
                published=published,
                source=source_label,
                snippet=summary[:500] if summary else title,
                provider=provider,
            )
        )
    return results


def discover_broad_google_news(
    query: str,
    *,
    date_from: date,
    date_to: date,
    max_total: int = 50,
) -> list[ArticleCandidate]:
    """Unrestricted Google News RSS — all publishers matching the query."""
    url = GOOGLE_NEWS_RSS.format(query=quote_plus(query))
    content = _fetch_feed(url)
    if not content:
        return []
    results = _parse_feed_entries(
        content,
        source_label="Google News",
        provider="broad:google-news",
        start=date_from,
        end=date_to,
        max_items=max_total,
    )
    logger.info("Broad Google News RSS: %d candidates", len(results))
    return results


def _outlet_rss_candidates(
    outlet: str,
    site_filter: str,
    topic_query: str,
    *,
    start: date,
    end: date,
    max_per_outlet: int,
) -> list[ArticleCandidate]:
    query = quote_plus(f"{topic_query} {site_filter}")
    url = GOOGLE_NEWS_RSS.format(query=query)
    content = _fetch_feed(url)
    if not content:
        return []
    return _parse_feed_entries(
        content,
        source_label=outlet,
        provider=f"outlet:{outlet}",
        start=start,
        end=end,
        max_items=max_per_outlet,
    )


def discover_outlet_feeds(
    query: str,
    *,
    date_from: date,
    date_to: date,
    max_total: int = 50,
    workers: int | None = None,
) -> list[ArticleCandidate]:
    """Parallel Google News RSS searches scoped to major outlets."""
    workers = workers or int(os.environ.get("DISCOVER_WORKERS", "8"))
    per_outlet = max(5, max_total // max(len(OUTLET_SEARCHES), 1))
    candidates: list[ArticleCandidate] = []
    seen: set[str] = set()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _outlet_rss_candidates,
                outlet,
                site_filter,
                query,
                start=date_from,
                end=date_to,
                max_per_outlet=per_outlet,
            ): outlet
            for outlet, site_filter in OUTLET_SEARCHES
        }
        for future in as_completed(futures):
            outlet = futures[future]
            try:
                batch = future.result()
            except Exception as exc:
                logger.warning("Outlet search failed %s: %s", outlet, exc)
                continue
            for c in batch:
                if c.url in seen:
                    continue
                seen.add(c.url)
                candidates.append(c)
                if len(candidates) >= max_total:
                    break

    logger.info(
        "Outlet RSS: %d candidates from %d outlets", len(candidates), len(OUTLET_SEARCHES)
    )
    return candidates[:max_total]

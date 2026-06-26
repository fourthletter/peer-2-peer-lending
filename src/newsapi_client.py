"""Optional NewsAPI.org discovery (Reuters, AP, and 150k+ outlets)."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time, timezone

import requests
from urllib.parse import urlparse

from src.article import ArticleCandidate
from src.newsapi_query import query_fallbacks, to_newsapi_query
from src.parse_dates import parse_published

logger = logging.getLogger(__name__)

NEWSAPI_URL = "https://newsapi.org/v2/everything"
DEFAULT_BUCKETS = ("asia", "africa", "latin_america")

# Set when NewsAPI returns 429; short-circuits remaining calls for the current run
# so we don't hammer a throttled API (free tier is ~100 requests/day).
_RATE_LIMITED = threading.Event()

# NewsAPI source ids — used when NEWS_API_USE_SOURCES=1 (legacy single call)
PREFERRED_SOURCES = (
    "reuters,associated-press,the-washington-post,bbc-news,"
    "financial-times,bloomberg,al-jazeera-english"
)


@dataclass(frozen=True)
class NewsApiBucket:
    key: str
    search_region: str
    domains: str = ""
    exclude_domains: str = ""


BUCKET_DEFINITIONS: dict[str, NewsApiBucket] = {
    "eu": NewsApiBucket(
        key="eu",
        search_region="newsapi:eu",
        domains=(
            "bbc.co.uk,bbc.com,theguardian.com,ft.com,reuters.com,"
            "economist.com,dw.com,euronews.com,independent.co.uk,politico.eu"
        ),
    ),
    "global_majority": NewsApiBucket(
        key="global_majority",
        search_region="newsapi:global_majority",
        domains=(
            "aljazeera.com,restofworld.org,scmp.com,japantimes.co.jp,"
            "straitstimes.com,hindustantimes.com,thehindu.com,"
            "channelnewsasia.com,allafrica.com,globalvoices.org"
        ),
        exclude_domains=(
            "nytimes.com,wsj.com,washingtonpost.com,cnn.com,cnbc.com,"
            "foxnews.com,latimes.com,usatoday.com,abcnews.com"
        ),
    ),
    "asia": NewsApiBucket(
        key="asia",
        search_region="newsapi:asia",
        domains=(
            "scmp.com,japantimes.co.jp,straitstimes.com,hindustantimes.com,"
            "thehindu.com,channelnewsasia.com,timesofindia.indiatimes.com,"
            "livemint.com,ndtv.com,globalvoices.org,techinasia.com,"
            "economictimes.indiatimes.com,indianexpress.com"
        ),
        exclude_domains=(
            "nytimes.com,wsj.com,cnn.com,cnbc.com,foxnews.com,bbc.com,"
            "theguardian.com"
        ),
    ),
    "africa": NewsApiBucket(
        key="africa",
        search_region="newsapi:africa",
        domains=(
            "allafrica.com,dailymaverick.co.za,mg.co.za,theafricareport.com,"
            "africanews.com,businessdailyafrica.com,businesstech.co.za,"
            "techcabal.com,nation.africa"
        ),
        exclude_domains=(
            "nytimes.com,wsj.com,cnn.com,cnbc.com,foxnews.com"
        ),
    ),
    "latin_america": NewsApiBucket(
        key="latin_america",
        search_region="newsapi:latin_america",
        domains=(
            "restofworld.org,folha.uol.com.br,elpais.com,lanacion.com.ar,"
            "clarin.com,emol.com,oglobo.globo.com,mexiconewsdaily.com,"
            "riotimesonline.com"
        ),
        exclude_domains=(
            "nytimes.com,wsj.com,cnn.com,cnbc.com,foxnews.com"
        ),
    ),
    "middle_east": NewsApiBucket(
        key="middle_east",
        search_region="newsapi:middle_east",
        domains=(
            "aljazeera.com,arabnews.com,middleeasteye.net,thenationalnews.com,"
            "haaretz.com,hurriyetdailynews.com,english.alarabiya.net,"
            "english.aawsat.com,trtworld.com"
        ),
        exclude_domains=(
            "nytimes.com,wsj.com,cnn.com,cnbc.com,foxnews.com"
        ),
    ),
    "open": NewsApiBucket(
        key="open",
        search_region="newsapi:open",
    ),
}


def active_bucket_keys() -> list[str]:
    raw = os.environ.get("NEWSAPI_BUCKETS", ",".join(DEFAULT_BUCKETS)).strip()
    keys = [k.strip().lower() for k in raw.split(",") if k.strip()]
    return [k for k in keys if k in BUCKET_DEFINITIONS]


def supplement_bucket_keys() -> list[str]:
    """Extra buckets when regional domain searches return too few articles."""
    raw = os.environ.get("NEWSAPI_SUPPLEMENT_BUCKETS", "global_majority").strip()
    keys = [k.strip().lower() for k in raw.split(",") if k.strip()]
    return [k for k in keys if k in BUCKET_DEFINITIONS]


def _domain_bucket_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for key, bucket in BUCKET_DEFINITIONS.items():
        if not bucket.domains:
            continue
        for domain in bucket.domains.split(","):
            domain = domain.strip().lower()
            if domain:
                mapping[domain] = key
    return mapping


def bucket_for_url(url: str, *, allowed: set[str] | None = None) -> str | None:
    """Map article URL host to a regional NewsAPI bucket key."""
    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return None
    if not host:
        return None
    for domain, bucket_key in _domain_bucket_map().items():
        if allowed is not None and bucket_key not in allowed:
            continue
        if host == domain or host.endswith("." + domain):
            return bucket_key
    return None


def _fetch_everything(
    api_key: str,
    *,
    query: str,
    date_from: date,
    date_to: date,
    page_size: int,
    bucket: NewsApiBucket,
    sort_by: str = "relevancy",
) -> list[dict]:
    params: dict[str, str | int] = {
        "q": query,
        "from": datetime.combine(date_from, time.min, tzinfo=timezone.utc).isoformat(),
        "to": datetime.combine(date_to, time.max, tzinfo=timezone.utc).isoformat(),
        "language": "en",
        "sortBy": sort_by,
        "pageSize": min(max(page_size, 1), 100),
        "apiKey": api_key,
    }
    if bucket.domains:
        params["domains"] = bucket.domains
    if bucket.exclude_domains:
        params["excludeDomains"] = bucket.exclude_domains

    if _RATE_LIMITED.is_set():
        return []

    try:
        resp = requests.get(NEWSAPI_URL, params=params, timeout=20)
    except requests.RequestException as exc:
        logger.warning("NewsAPI request failed (%s): %s", bucket.key, exc)
        return []

    if resp.status_code == 429:
        if not _RATE_LIMITED.is_set():
            logger.warning(
                "NewsAPI rate limited (429); skipping remaining NewsAPI calls "
                "this run. Free tier allows ~100 requests/day."
            )
        _RATE_LIMITED.set()
        return []

    try:
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("NewsAPI request failed (%s): %s", bucket.key, exc)
        return []

    if data.get("status") != "ok":
        logger.warning("NewsAPI error (%s): %s", bucket.key, data.get("message"))
        return []

    return data.get("articles", [])


def _fetch_with_query_fallbacks(
    api_key: str,
    *,
    query: str,
    date_from: date,
    date_to: date,
    page_size: int,
    bucket: NewsApiBucket,
) -> list[dict]:
    """Try relaxed boolean queries when the primary query returns no articles."""
    for attempt, q in enumerate(query_fallbacks(query)):
        if _RATE_LIMITED.is_set():
            return []
        articles = _fetch_everything(
            api_key,
            query=q,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            bucket=bucket,
        )
        if articles:
            if attempt > 0:
                logger.info(
                    "NewsAPI %s: relaxed query %r returned %d articles",
                    bucket.key,
                    q,
                    len(articles),
                )
            return articles
    return []


def _articles_to_candidates(
    articles: list[dict],
    *,
    bucket: NewsApiBucket,
    limit: int,
) -> list[ArticleCandidate]:
    candidates: list[ArticleCandidate] = []
    for article in articles:
        if len(candidates) >= limit:
            break
        url = (article.get("url") or "").strip()
        title = (article.get("title") or "").strip()
        if not url or not title or title.endswith(" - Removed"):
            continue
        published = parse_published(article.get("publishedAt"))
        source_name = (article.get("source") or {}).get("name", "NewsAPI")
        snippet = (article.get("description") or article.get("content") or "")[:500]
        candidates.append(
            ArticleCandidate(
                headline=title,
                url=url,
                published=published,
                source=source_name,
                snippet=snippet,
                search_region=bucket.search_region,
                provider="newsapi",
            )
        )
    return candidates


def _discover_single_call(
    query: str,
    *,
    date_from: date,
    date_to: date,
    max_results: int,
    api_key: str,
) -> list[ArticleCandidate]:
    """Legacy single-request mode when NEWS_API_USE_SOURCES=1."""
    params = {
        "q": query,
        "from": datetime.combine(date_from, time.min, tzinfo=timezone.utc).isoformat(),
        "to": datetime.combine(date_to, time.max, tzinfo=timezone.utc).isoformat(),
        "language": "en",
        "sortBy": "relevancy",
        "pageSize": min(max_results, 100),
        "apiKey": api_key,
        "sources": PREFERRED_SOURCES,
    }
    try:
        resp = requests.get(NEWSAPI_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("NewsAPI request failed: %s", exc)
        return []
    if data.get("status") != "ok":
        logger.warning("NewsAPI error: %s", data.get("message"))
        return []

    bucket = BUCKET_DEFINITIONS["open"]
    return _articles_to_candidates(
        data.get("articles", []),
        bucket=bucket,
        limit=max_results,
    )


def _fetch_bucket(
    bucket_key: str,
    *,
    query: str,
    date_from: date,
    date_to: date,
    per_bucket: int,
    api_key: str,
) -> tuple[str, list[ArticleCandidate]]:
    bucket = BUCKET_DEFINITIONS[bucket_key]
    articles = _fetch_with_query_fallbacks(
        api_key,
        query=query,
        date_from=date_from,
        date_to=date_to,
        page_size=per_bucket,
        bucket=bucket,
    )
    candidates = _articles_to_candidates(articles, bucket=bucket, limit=per_bucket)
    return bucket_key, candidates


def _supplement_from_buckets(
    query: str,
    *,
    date_from: date,
    date_to: date,
    per_bucket: int,
    api_key: str,
    supplement_keys: list[str],
    target_buckets: set[str],
) -> dict[str, list[ArticleCandidate]]:
    """Fetch from broader buckets and assign articles to regional buckets by domain."""
    batches: dict[str, list[ArticleCandidate]] = {k: [] for k in target_buckets}
    allowed = set(target_buckets)

    for sup_key in supplement_keys:
        if sup_key in target_buckets:
            continue
        bucket = BUCKET_DEFINITIONS[sup_key]
        articles = _fetch_with_query_fallbacks(
            api_key,
            query=query,
            date_from=date_from,
            date_to=date_to,
            page_size=per_bucket * 2,
            bucket=bucket,
        )
        for article in articles:
            url = (article.get("url") or "").strip()
            title = (article.get("title") or "").strip()
            snippet = (article.get("description") or article.get("content") or "")[:500]
            region_key = bucket_for_url(url, allowed=allowed)
            if not region_key:
                from src.article import ArticleCandidate
                from src.thematic_regions import article_matches_theme

                probe = ArticleCandidate(
                    headline=title,
                    url=url,
                    published=None,
                    source=(article.get("source") or {}).get("name", ""),
                    snippet=snippet,
                    search_region=f"newsapi:{sup_key}",
                    provider="newsapi",
                )
                for key in allowed:
                    if article_matches_theme(probe, key):
                        region_key = key
                        break
            if not region_key:
                continue
            region_bucket = BUCKET_DEFINITIONS[region_key]
            candidate_list = _articles_to_candidates(
                [article],
                bucket=region_bucket,
                limit=1,
            )
            if candidate_list:
                batches[region_key].append(candidate_list[0])

    return batches


def _merge_batches_round_robin(
    batches: dict[str, list[ArticleCandidate]],
    bucket_keys: list[str],
    *,
    max_total: int,
) -> list[ArticleCandidate]:
    merged: list[ArticleCandidate] = []
    seen: set[str] = set()
    indices = {k: 0 for k in bucket_keys}

    while len(merged) < max_total:
        progressed = False
        for key in bucket_keys:
            pool = batches.get(key, [])
            idx = indices[key]
            while idx < len(pool):
                c = pool[idx]
                indices[key] = idx + 1
                idx += 1
                if c.url in seen:
                    continue
                seen.add(c.url)
                merged.append(c)
                progressed = True
                break
            if len(merged) >= max_total:
                break
        if not progressed:
            break
    return merged


def discover_newsapi(
    query: str,
    *,
    date_from: date,
    date_to: date,
    max_results: int = 30,
    bucket_keys: list[str] | None = None,
) -> list[ArticleCandidate]:
    api_key = os.environ.get("NEWS_API_KEY", "").strip()
    if not api_key:
        return []

    _RATE_LIMITED.clear()

    if os.environ.get("NEWS_API_USE_SOURCES", "0") == "1":
        results = _discover_single_call(
            query,
            date_from=date_from,
            date_to=date_to,
            max_results=max_results,
            api_key=api_key,
        )
        logger.info("NewsAPI (sources mode): %d candidates", len(results))
        return results

    if bucket_keys is None:
        bucket_keys = active_bucket_keys()
    if not bucket_keys:
        bucket_keys = list(DEFAULT_BUCKETS)

    newsapi_query = to_newsapi_query(query)
    per_bucket = max(10, max_results // max(len(bucket_keys), 1))
    workers = int(os.environ.get("FETCH_WORKERS", "6"))
    batches: dict[str, list[ArticleCandidate]] = {}

    with ThreadPoolExecutor(max_workers=min(workers, len(bucket_keys))) as pool:
        futures = {
            pool.submit(
                _fetch_bucket,
                key,
                query=newsapi_query,
                date_from=date_from,
                date_to=date_to,
                per_bucket=per_bucket,
                api_key=api_key,
            ): key
            for key in bucket_keys
        }
        for future in as_completed(futures):
            key, candidates = future.result()
            batches[key] = candidates
            logger.info("NewsAPI %s: %d candidates", key, len(candidates))

    merged = _merge_batches_round_robin(
        batches, bucket_keys, max_total=max_results
    )

    min_before_supplement = max(
        3, int(os.environ.get("NEWSAPI_MIN_BEFORE_SUPPLEMENT", "8"))
    )
    empty_buckets = [k for k in bucket_keys if not batches.get(k)]
    needs_supplement = len(merged) < min_before_supplement or bool(empty_buckets)
    if needs_supplement and not _RATE_LIMITED.is_set():
        supplement_keys = supplement_bucket_keys()
        if supplement_keys:
            target = set(empty_buckets) if empty_buckets else set(bucket_keys)
            extra = _supplement_from_buckets(
                newsapi_query,
                date_from=date_from,
                date_to=date_to,
                per_bucket=per_bucket,
                api_key=api_key,
                supplement_keys=supplement_keys,
                target_buckets=target,
            )
            for key, candidates in extra.items():
                if not candidates:
                    continue
                existing = batches.setdefault(key, [])
                seen_urls = {c.url for c in existing}
                added = 0
                for c in candidates:
                    if c.url not in seen_urls:
                        existing.append(c)
                        seen_urls.add(c.url)
                        added += 1
                if added:
                    logger.info(
                        "NewsAPI supplement → %s: +%d candidates",
                        key,
                        added,
                    )
            merged = _merge_batches_round_robin(
                batches, bucket_keys, max_total=max_results
            )

    logger.info(
        "NewsAPI merged: %d candidates from buckets %s (query=%r)",
        len(merged),
        ", ".join(bucket_keys),
        newsapi_query[:80],
    )
    return merged

"""Core digest pipeline shared by CLI and web UI."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from dotenv import load_dotenv

from src.config import DigestConfig
from src.coverage import format_coverage_label, infer_publisher_country
from src.discovery_hub import discover_all
from src.thematic_regions import (
    classify_thematic_region,
    ddgs_regions_for_themes,
    format_filter_summary,
    newsapi_buckets_for_themes,
)
from src.digest import format_html, format_plain, subject_line
from src.emailer import send_digest
from src.fetch import canonical_article_url, enrich_candidates_parallel
from src.text_utils import strip_html
from src.rank import rank_articles, rank_by_eventregistry_score, rank_use_er_score
from src.storage import load_sent_urls, normalize_url, save_sent_urls
from src.summarize import DigestArticle, llm_summary_enabled, summarize_articles

load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class DigestResult:
    articles: list[DigestArticle]
    plain: str
    html: str
    subject: str
    note: str
    discovered: int
    new_candidates: int
    ranked_count: int
    coverage_label: str = ""
    filter_summary: str = ""
    search_query: str = ""


def _date_range_label(config: DigestConfig) -> str:
    return (
        f"{config.date_from.strftime('%b %d, %Y')} – "
        f"{config.date_to.strftime('%b %d, %Y')}"
    )


def _fast_rank_enabled() -> bool:
    return os.environ.get("FAST_RANK", "1") == "1"


def _rank_pool(candidates: list, max_to_rank: int) -> list:
    """Prefer Event Registry articles (sorted by API relevance) for the ranking pool."""
    er = sorted(
        [c for c in candidates if c.provider == "eventregistry"],
        key=lambda c: c.relevance_score,
        reverse=True,
    )
    other = [c for c in candidates if c.provider != "eventregistry"]
    if rank_use_er_score() and er:
        pool = er[:max_to_rank]
        if len(pool) < max_to_rank:
            pool.extend(other[: max_to_rank - len(pool)])
        return pool
    return candidates[:max_to_rank]


def build_digest(
    config: DigestConfig,
    *,
    dry_run: bool = False,
    send_email: bool = False,
) -> DigestResult:
    """Discover, rank, summarize, and optionally email a digest."""
    sent = load_sent_urls()
    ddgs_regions = ddgs_regions_for_themes(list(config.geographic_regions))
    newsapi_buckets = newsapi_buckets_for_themes(list(config.geographic_regions))
    global_coverage = config.global_coverage and ddgs_regions is None

    candidates = discover_all(
        query=config.query,
        max_candidates=config.discover_max_results,
        date_from=config.date_from,
        date_to=config.date_to,
        global_coverage=global_coverage,
        regions=ddgs_regions,
        newsapi_only=config.newsapi_only,
        newsapi_bucket_keys=newsapi_buckets,
        theme_region_keys=list(config.geographic_regions),
    )
    # Note: Google News / redirect URLs are resolved later, in parallel, only for
    # the final ranked winners (see enrich + the canonicalization loop below).
    # Canonicalizing every candidate here would make one network call per article.

    discovered_raw = len(candidates)
    # Soft region handling: keep every candidate and let ranking apply a regional
    # boost (see rank_articles). Selected regions still steer discovery buckets,
    # but we no longer hard-drop global stories that don't match a focus country.
    for c in candidates:
        c.thematic_region = classify_thematic_region(c)

    logger.info("Discovered %d candidates", discovered_raw)
    logger.info("Already sent: %d URLs", len(sent))

    if config.skip_dedup:
        new_candidates = candidates
    else:
        new_candidates = [
            c for c in candidates if normalize_url(c.url) not in sent
        ]
    logger.info("New candidates after dedup: %d", len(new_candidates))

    pool = _rank_pool(new_candidates, config.max_to_rank)
    fast_rank = _fast_rank_enabled()
    er_in_pool = sum(1 for c in pool if c.provider == "eventregistry")
    use_er_rank = rank_use_er_score() and er_in_pool >= config.article_count

    # Fast path: rank on snippets only, then fetch full text for winners
    lightweight = []
    for c in pool:
        lightweight.append(
            {
                "headline": c.headline,
                "url": c.url,
                "snippet": strip_html(c.snippet),
                "text": strip_html(c.snippet) or c.headline,
                "source": c.source,
                "provider": c.provider,
                "published": c.published,
                "search_region": c.search_region,
                "thematic_region": c.thematic_region,
                "publisher_country": c.location_country
                or infer_publisher_country(source=c.source, url=c.url),
                "concepts": c.concepts,
                "companies": c.companies,
                "relevance_score": c.relevance_score,
            }
        )

    if use_er_rank:
        logger.info(
            "Ranking %d Event Registry candidates by API relevance (no LLM)",
            er_in_pool,
        )
        ranked = rank_by_eventregistry_score(
            lightweight,
            top_n=config.article_count,
            geographic_regions=config.geographic_regions,
        )
        if not llm_summary_enabled():
            for r in ranked:
                if not r.snippet:
                    r.snippet = r.text
    elif fast_rank:
        logger.info("Fast rank: scoring %d candidates on snippets", len(lightweight))
        ranked = rank_articles(
            lightweight,
            top_n=config.article_count,
            max_to_rank=config.max_to_rank,
            geographic_regions=config.geographic_regions,
        )
        if llm_summary_enabled():
            finalists = [
                {
                    "headline": r.headline,
                    "url": r.url,
                    "snippet": r.snippet or r.text,
                    "source": r.source,
                    "published": r.published,
                    "search_region": r.search_region,
                    "thematic_region": r.thematic_region,
                }
                for r in ranked
            ]
            enriched = enrich_candidates_parallel(finalists, fetch_full=True)
            for i, row in enumerate(enriched):
                if i < len(ranked):
                    ranked[i].text = row.get("text") or ranked[i].text
                    if row.get("url"):
                        ranked[i].url = row["url"]
        else:
            logger.info(
                "SUMMARY_LLM=0: keeping discovery snippets (no full-article fetch)"
            )
            for r in ranked:
                if not r.snippet:
                    r.snippet = r.text
    elif not use_er_rank:
        enriched = enrich_candidates_parallel(
            [
                {
                    "headline": c.headline,
                    "url": c.url,
                    "snippet": c.snippet,
                    "source": c.source,
                    "published": c.published,
                    "search_region": c.search_region,
                    "thematic_region": c.thematic_region,
                }
                for c in pool
            ],
            fetch_full=True,
        )
        ranked = rank_articles(
            enriched,
            top_n=config.article_count,
            max_to_rank=config.max_to_rank,
            geographic_regions=config.geographic_regions,
        )

    logger.info("Top ranked: %d articles", len(ranked))

    note = ""
    if not candidates and discovered_raw == 0:
        note = (
            "No articles were found for this date range and query. "
            "Try a wider date range, fewer focus keywords, or check EVENTREGISTRY_API_KEY. "
        )
    elif ranked and len(ranked) < config.article_count:
        note = (
            f"Only {len(ranked)} article(s) met the relevance threshold "
            f"(requested {config.article_count})."
        )

    # Resolve redirect/wrapper URLs for the few winners in parallel (each is a
    # blocking network call, so a sequential loop adds noticeable latency).
    if ranked:
        workers = min(len(ranked), int(os.environ.get("FETCH_WORKERS", "6")))
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as cpool:
            canon_urls = list(cpool.map(canonical_article_url, [a.url for a in ranked]))
        for article, url in zip(ranked, canon_urls):
            article.url = url
            if not article.publisher_country:
                article.publisher_country = infer_publisher_country(
                    source=article.source,
                    url=article.url,
                )
        # Different discovery sources can wrap the same story (e.g. a Google News
        # link and the publisher feed); they only collapse once canonicalized, so
        # dedup again here to avoid duplicate cards.
        deduped: list = []
        seen_urls: set[str] = set()
        for article in ranked:
            key = normalize_url(article.url)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            deduped.append(article)
        ranked = deduped

    digest_articles = summarize_articles(ranked) if ranked else []

    range_label = _date_range_label(config)
    coverage_label = format_coverage_label(config)
    filter_summary = format_filter_summary(
        theme_ids=list(config.geographic_regions),
        extra_keywords=config.extra_keywords,
    )
    subject = subject_line(range_label)
    plain = format_plain(
        digest_articles,
        note=note,
        title_suffix=range_label,
        coverage_label=coverage_label,
    )
    html = format_html(
        digest_articles,
        note=note,
        title_suffix=range_label,
        coverage_label=coverage_label,
    )

    result = DigestResult(
        articles=digest_articles,
        plain=plain,
        html=html,
        subject=subject,
        note=note,
        discovered=len(candidates),
        new_candidates=len(new_candidates),
        ranked_count=len(ranked),
        coverage_label=coverage_label,
        filter_summary=filter_summary,
        search_query=config.query,
    )

    if dry_run:
        return result

    if send_email:
        send_digest(subject, plain, html)
        if digest_articles:
            urls = [a.url for a in digest_articles]
            save_sent_urls(sent, urls)
            logger.info("Recorded %d sent URLs", len(urls))

    return result

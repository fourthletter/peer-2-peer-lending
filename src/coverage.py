"""Discovery coverage labels and publisher country inference."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from src.config import DigestConfig
from src.regions import GLOBAL_NEWS_REGIONS, resolve_regions

_REGION_LABELS: dict[str, str] = {code: label for code, label in GLOBAL_NEWS_REGIONS}

# Publisher HQ by outlet name (case-insensitive keys)
_PUBLISHER_BY_NAME: dict[str, str] = {
    "reuters": "United Kingdom",
    "associated press": "United States",
    "ap news": "United States",
    "bbc": "United Kingdom",
    "bbc news": "United Kingdom",
    "the guardian": "United Kingdom",
    "guardian": "United Kingdom",
    "npr": "United States",
    "financial times": "United Kingdom",
    "bloomberg": "United States",
    "wall street journal": "United States",
    "the wall street journal": "United States",
    "new york times": "United States",
    "the new york times": "United States",
    "washington post": "United States",
    "the washington post": "United States",
    "cnbc": "United States",
    "al jazeera": "Qatar",
    "al jazeera english": "Qatar",
    "economist": "United Kingdom",
    "the economist": "United Kingdom",
    "techcrunch": "United States",
    "wired": "United States",
    "mit technology review": "United States",
    "harvard business review": "United States",
    "ilo": "Switzerland",
    "world economic forum": "Switzerland",
    "rest of world": "United States",
    "google news": "United States",
    "reddit": "United States",
    "newsapi": "United States",
}

# Publisher HQ by registrable domain
_PUBLISHER_BY_DOMAIN: dict[str, str] = {
    "reuters.com": "United Kingdom",
    "apnews.com": "United States",
    "bbc.com": "United Kingdom",
    "bbc.co.uk": "United Kingdom",
    "theguardian.com": "United Kingdom",
    "npr.org": "United States",
    "ft.com": "United Kingdom",
    "bloomberg.com": "United States",
    "wsj.com": "United States",
    "nytimes.com": "United States",
    "washingtonpost.com": "United States",
    "cnbc.com": "United States",
    "aljazeera.com": "Qatar",
    "economist.com": "United Kingdom",
    "techcrunch.com": "United States",
    "wired.com": "United States",
    "technologyreview.com": "United States",
    "hbr.org": "United States",
    "ilo.org": "Switzerland",
    "weforum.org": "Switzerland",
    "restofworld.org": "United States",
    "scmp.com": "Hong Kong",
    "straitstimes.com": "Singapore",
    "channelnewsasia.com": "Singapore",
    "japantimes.co.jp": "Japan",
    "hindustantimes.com": "India",
    "thehindu.com": "India",
    "livemint.com": "India",
    "ndtv.com": "India",
    "allafrica.com": "Kenya",
    "dailymaverick.co.za": "South Africa",
    "mg.co.za": "South Africa",
    "theafricareport.com": "France",
    "africanews.com": "France",
    "businessdailyafrica.com": "Kenya",
    "businesstech.co.za": "South Africa",
    "techcabal.com": "Nigeria",
    "folha.uol.com.br": "Brazil",
    "lanacion.com.ar": "Argentina",
    "clarin.com": "Argentina",
    "oglobo.globo.com": "Brazil",
    "globalvoices.org": "Netherlands",
}


def region_display_name(region_code: str) -> str:
    """Human label for a DDGS region code."""
    if not region_code:
        return ""
    if region_code == "reddit":
        return "Reddit (global)"
    return _REGION_LABELS.get(region_code, region_code)


def infer_publisher_country(*, source: str, url: str) -> str:
    """Best-effort country where the news organization is headquartered."""
    name = (source or "").strip().lower()
    if name:
        if name in _PUBLISHER_BY_NAME:
            return _PUBLISHER_BY_NAME[name]
        for key, country in _PUBLISHER_BY_NAME.items():
            if key in name or name in key:
                return country

    try:
        host = urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        host = ""
    if host:
        for domain, country in _PUBLISHER_BY_DOMAIN.items():
            if host == domain or host.endswith("." + domain):
                return country
        if host.endswith(".co.uk"):
            return "United Kingdom"
        if host.endswith(".com.au"):
            return "Australia"
        if host.endswith(".ca"):
            return "Canada"
        if host.endswith(".de"):
            return "Germany"
        if host.endswith(".fr"):
            return "France"
        if host.endswith(".in"):
            return "India"
        if host.endswith(".jp"):
            return "Japan"

    return ""


def discovery_region_label(search_region: str) -> str:
    """Human label for a discovery bucket tag (e.g. newsapi:eu)."""
    tag = (search_region or "").strip()
    labels = {
        "newsapi:eu": "Europe",
        "newsapi:global_majority": "Global Majority",
        "newsapi:asia": "Asia",
        "newsapi:africa": "Africa",
        "newsapi:latin_america": "Latin America",
        "newsapi:open": "Open English",
    }
    if tag == "eventregistry" or tag.startswith("eventregistry:"):
        return "Event Registry"
    return labels.get(tag, "")


def format_newsapi_coverage_label() -> str:
    from src.newsapi_client import active_bucket_keys

    names: list[str] = []
    for key in active_bucket_keys():
        label = discovery_region_label(f"newsapi:{key}")
        if label:
            names.append(label)
    if not names:
        names = ["Europe", "Global Majority", "open English"]
    return "NewsAPI: " + ", ".join(names)


def format_coverage_label(config: DigestConfig) -> str:
    """Countries/regions included in this run's news discovery."""
    from src.thematic_regions import (
        format_filter_summary,
        newsapi_buckets_for_themes,
        THEMATIC_REGIONS,
    )

    src = os.environ.get("DISCOVERY_SOURCE", "").strip().lower()
    if src == "split":
        from src.thematic_regions import split_discovery_plan

        plan = split_discovery_plan(list(config.geographic_regions))
        parts: list[str] = []
        if plan.use_newsapi:
            parts.append("NewsAPI (Europe & North America)")
        if plan.use_eventregistry:
            parts.append("Event Registry (Asia, Africa, Latin America, Middle East)")
        return "; ".join(parts) if parts else "Split discovery (no regions selected)"
    if src == "eventregistry":
        mode = os.environ.get("EVENTREGISTRY_QUERY_MODE", "ai_export").strip().lower()
        scope = "AI + labor" if mode != "ai" else "AI (global)"
        return f"Event Registry: {scope}, 150k+ sources with concept tags"
    if config.newsapi_only:
        base = format_newsapi_coverage_label()
        buckets = newsapi_buckets_for_themes(list(config.geographic_regions))
        if buckets:
            names = []
            for key in buckets:
                if key == "eu":
                    names.append("Europe")
                elif key == "global_majority":
                    names.append("Global Majority")
                elif key == "open":
                    names.append("open English")
            if names:
                base = "NewsAPI: " + ", ".join(names)
        elif config.geographic_regions:
            labels = [
                THEMATIC_REGIONS[t].label
                for t in config.geographic_regions
                if t in THEMATIC_REGIONS
            ]
            if labels:
                base = "NewsAPI (focused): " + ", ".join(labels)
        extra = format_filter_summary(
            theme_ids=list(config.geographic_regions),
            extra_keywords=config.extra_keywords,
        )
        if extra and "Regions:" in extra:
            return f"{base}. {extra}"
        return base

    parts: list[str] = []
    regions = resolve_regions(global_coverage=config.global_coverage)
    names: list[str] = []
    seen: set[str] = set()
    for code in regions:
        label = region_display_name(code)
        if label and label not in seen:
            seen.add(label)
            names.append(label)

    if names:
        if len(names) <= 10:
            parts.append(", ".join(names))
        else:
            preview = ", ".join(names[:8])
            parts.append(f"{preview}, and {len(names) - 8} more")

    extras: list[str] = []
    if os.environ.get("ENABLE_OUTLET_FEEDS", "1") == "1":
        extras.append(
            "major international outlets (Reuters, AP, BBC, NYT, Bloomberg, etc.)"
        )
    if os.environ.get("ENABLE_BROAD_NEWS", "1") == "1":
        extras.append("broad Google News search")
    if os.environ.get("ENABLE_NEWSAPI", "0") == "1" and os.environ.get(
        "NEWS_API_KEY", ""
    ).strip():
        extras.append("NewsAPI publishers")
    if (
        os.environ.get("ENABLE_EVENTREGISTRY", "1") == "1"
        and os.environ.get("EVENTREGISTRY_API_KEY", "").strip()
    ):
        extras.append("Event Registry (150k+ global sources)")
    if os.environ.get("ENABLE_REDDIT", "1") == "1":
        extras.append("Reddit")

    if extras:
        extra_text = "; ".join(extras)
        if parts:
            parts[0] = f"{parts[0]}; plus {extra_text}"
        else:
            parts.append(extra_text)

    return parts[0] if parts else "United States"


def format_publisher_line(*, source: str, publisher_country: str) -> str:
    """Single-line publisher attribution for digest entries."""
    outlet = (source or "").strip()
    country = (publisher_country or "").strip()
    if outlet and country:
        return f"{outlet} · based in {country}"
    if outlet:
        return outlet
    if country:
        return f"Publisher based in {country}"
    return ""

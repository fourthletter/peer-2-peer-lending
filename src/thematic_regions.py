"""Thematic geographic regions, keyword query building, and article filtering."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from src.article import ArticleCandidate
from src.discover import DEFAULT_QUERY

EUROPE_COUNTRIES = frozenset(
    {
        "United Kingdom",
        "Germany",
        "France",
        "Spain",
        "Italy",
        "Netherlands",
        "Poland",
        "Switzerland",
        "Belgium",
        "Sweden",
        "Norway",
        "Denmark",
        "Finland",
        "Ireland",
        "Austria",
        "Portugal",
        "Greece",
        "Czech Republic",
        "Romania",
        "Hungary",
    }
)

NORTH_AMERICA_COUNTRIES = frozenset(
    {
        "United States",
        "Canada",
    }
)

ASIA_COUNTRIES = frozenset(
    {
        "India",
        "Japan",
        "China",
        "South Korea",
        "Singapore",
        "Australia",
        "Hong Kong",
        "Taiwan",
        "Malaysia",
        "Pakistan",
        "Bangladesh",
        "Philippines",
        "Thailand",
        "Vietnam",
        "Indonesia",
    }
)

AFRICA_COUNTRIES = frozenset(
    {
        "South Africa",
        "Nigeria",
        "Kenya",
        "Egypt",
        "Ghana",
        "Ethiopia",
        "Morocco",
        "Tanzania",
    }
)

LATIN_AMERICA_COUNTRIES = frozenset(
    {
        "Brazil",
        "Mexico",
        "Argentina",
        "Colombia",
        "Chile",
        "Peru",
    }
)

MIDDLE_EAST_COUNTRIES = frozenset(
    {
        "Qatar",
        "United Arab Emirates",
        "Saudi Arabia",
        "Israel",
        "Turkey",
        "Egypt",
    }
)


@dataclass(frozen=True)
class ThematicRegion:
    id: str
    label: str
    ddgs_codes: tuple[str, ...]
    newsapi_buckets: tuple[str, ...]
    countries: frozenset[str]
    content_keywords: tuple[str, ...]


THEMATIC_REGIONS: dict[str, ThematicRegion] = {
    "global": ThematicRegion(
        id="global",
        label="Global",
        ddgs_codes=("wt-wt",),
        newsapi_buckets=("eu", "global_majority", "open"),
        countries=frozenset(),
        content_keywords=(),
    ),
    "europe": ThematicRegion(
        id="europe",
        label="Europe",
        ddgs_codes=("uk-en", "de-de", "fr-fr", "es-es", "it-it", "nl-nl", "pl-pl"),
        newsapi_buckets=("eu", "open"),
        countries=EUROPE_COUNTRIES,
        content_keywords=(
            "europe",
            "european",
            "uk",
            "britain",
            "germany",
            "france",
            "eu ",
        ),
    ),
    "north_america": ThematicRegion(
        id="north_america",
        label="North America",
        ddgs_codes=("us-en", "ca-en"),
        newsapi_buckets=("open",),
        countries=NORTH_AMERICA_COUNTRIES,
        content_keywords=(
            "united states",
            "u.s.",
            "america",
            "canada",
            "california",
            "new york",
        ),
    ),
    "asia": ThematicRegion(
        id="asia",
        label="Asia",
        ddgs_codes=(
            "in-en",
            "jp-jp",
            "kr-kr",
            "cn-zh",
            "id-id",
            "ph-en",
            "th-en",
            "vn-en",
            "sg-en",
            "hk-en",
            "tw-en",
            "my-en",
            "pk-en",
            "bd-en",
        ),
        newsapi_buckets=("asia",),
        countries=ASIA_COUNTRIES,
        content_keywords=(
            "asia",
            "asian",
            "india",
            "china",
            "japan",
            "bangladesh",
            "vietnam",
            "garment",
            "southeast asia",
        ),
    ),
    "africa": ThematicRegion(
        id="africa",
        label="Africa",
        ddgs_codes=("za-en", "ng-en", "ke-en", "eg-ar"),
        newsapi_buckets=("africa",),
        countries=AFRICA_COUNTRIES,
        content_keywords=(
            "africa",
            "african",
            "nigeria",
            "kenya",
            "south africa",
            "egypt",
            "lagos",
            "nairobi",
            "johannesburg",
            "sub-saharan",
        ),
    ),
    "latin_america": ThematicRegion(
        id="latin_america",
        label="Latin America",
        ddgs_codes=("br-pt", "mx-es", "ar-es", "co-es", "cl-es", "pe-es"),
        newsapi_buckets=("latin_america",),
        countries=LATIN_AMERICA_COUNTRIES,
        content_keywords=(
            "latin america",
            "brazil",
            "mexico",
            "argentina",
            "colombia",
            "chile",
        ),
    ),
    "middle_east": ThematicRegion(
        id="middle_east",
        label="Middle East",
        ddgs_codes=("ae-ar", "sa-ar", "il-en", "tr-tr", "eg-ar"),
        newsapi_buckets=("global_majority", "open"),
        countries=MIDDLE_EAST_COUNTRIES,
        content_keywords=(
            "middle east",
            "gulf",
            "qatar",
            "saudi",
            "uae",
            "israel",
            "turkey",
        ),
    ),
}

UI_REGION_ORDER = (
    "global",
    "europe",
    "asia",
    "africa",
    "latin_america",
    "middle_east",
    "north_america",
)

_NEWSAPI_BUCKET_THEMES: dict[str, str] = {
    "newsapi:eu": "europe",
    "newsapi:global_majority": "global_majority",  # resolved via country/content
}


def parse_keyword_phrases(raw: str) -> list[str]:
    if not raw or not raw.strip():
        return []
    return [p.strip() for p in re.split(r"[,;\n]+", raw) if p.strip()]


def build_search_query(base: str, extra_keywords: str) -> str:
    """Combine base labor/AI query with optional user keyword phrases (OR group)."""
    phrases = parse_keyword_phrases(extra_keywords)
    if not phrases:
        return base
    parts: list[str] = []
    for phrase in phrases:
        parts.append(f'"{phrase}"' if " " in phrase else phrase)
    return f"({base}) ({' OR '.join(parts)})"


DEFAULT_FOCUS_REGIONS = ("asia", "africa", "latin_america", "middle_east")


def default_geographic_regions() -> tuple[str, ...]:
    """Default thematic focus from DEFAULT_GEOGRAPHIC_REGIONS env.

    Defaults to Global (empty selection) so ranking sees the full candidate pool;
    set DEFAULT_GEOGRAPHIC_REGIONS=asia,africa,latin_america,middle_east to refocus.
    """
    raw = os.environ.get("DEFAULT_GEOGRAPHIC_REGIONS", "global")
    ids = normalize_region_selection([s.strip() for s in raw.split(",") if s.strip()])
    return tuple(ids)


def normalize_region_selection(selected: list[str]) -> list[str]:
    ids = [s.strip().lower() for s in selected if s.strip()]
    if not ids or "global" in ids:
        return []
    return [i for i in ids if i in THEMATIC_REGIONS and i != "global"]


def resolve_pick_order(theme_ids: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Round-robin order for ranking; defaults to Africa / Asia / Latin America focus."""
    ids = list(theme_ids) if theme_ids else list(default_geographic_regions())
    ids = normalize_region_selection(ids)
    if not ids:
        return DEFAULT_FOCUS_REGIONS
    order = [t for t in DEFAULT_FOCUS_REGIONS if t in ids]
    for tid in ids:
        if tid not in order:
            order.append(tid)
    return tuple(order)


def ddgs_regions_for_themes(theme_ids: list[str]) -> list[str] | None:
    """DDGS region codes for selected themes; None = default global coverage.

    Codes are round-robined across the selected themes so a capped list still
    covers every region, then limited by DDGS_MAX_REGIONS (each code is a
    separate, rate-limited DuckDuckGo call, so fewer = much faster).
    """
    theme_ids = normalize_region_selection(theme_ids)
    if not theme_ids:
        return None

    per_theme = [list(THEMATIC_REGIONS[tid].ddgs_codes) for tid in theme_ids]
    codes: list[str] = []
    seen: set[str] = set()
    i = 0
    while any(i < len(codes_list) for codes_list in per_theme):
        for codes_list in per_theme:
            if i < len(codes_list):
                code = codes_list[i]
                if code not in seen:
                    seen.add(code)
                    codes.append(code)
        i += 1

    max_regions = int(os.environ.get("DDGS_MAX_REGIONS", "8"))
    if max_regions > 0:
        codes = codes[:max_regions]
    return codes or None


def newsapi_buckets_for_themes(theme_ids: list[str]) -> list[str] | None:
    """NewsAPI bucket keys for selected themes; None = use env default."""
    theme_ids = normalize_region_selection(theme_ids)
    if not theme_ids:
        return None
    buckets: list[str] = []
    seen: set[str] = set()
    for tid in theme_ids:
        for key in THEMATIC_REGIONS[tid].newsapi_buckets:
            if key not in seen:
                seen.add(key)
                buckets.append(key)
    return buckets or None


# Split discovery (DISCOVERY_SOURCE=split): NewsAPI for Western buckets, ER elsewhere.
NEWSAPI_DISCOVERY_THEMES = frozenset({"europe", "north_america"})
EVENTREGISTRY_DISCOVERY_THEMES = frozenset(
    {"asia", "africa", "latin_america", "middle_east"}
)
SPLIT_NEWSAPI_GLOBAL_BUCKETS = ("eu", "open")


@dataclass(frozen=True)
class SplitDiscoveryPlan:
    """Which provider(s) to call for the current regional focus."""

    use_eventregistry: bool
    use_newsapi: bool
    eventregistry_theme_keys: tuple[str, ...] | None
    newsapi_bucket_keys: tuple[str, ...] | None


def split_discovery_plan(theme_ids: list[str] | tuple[str, ...]) -> SplitDiscoveryPlan:
    """Route discovery: NewsAPI for Europe / North America, Event Registry for other themes.

    Empty theme list (Global) runs both providers with their default global scope.
    """
    themes = normalize_region_selection(list(theme_ids))
    if not themes:
        buckets = newsapi_buckets_for_themes(
            list(NEWSAPI_DISCOVERY_THEMES)
        ) or list(SPLIT_NEWSAPI_GLOBAL_BUCKETS)
        return SplitDiscoveryPlan(
            use_eventregistry=True,
            use_newsapi=True,
            eventregistry_theme_keys=None,
            newsapi_bucket_keys=tuple(buckets),
        )

    newsapi_themes = [t for t in themes if t in NEWSAPI_DISCOVERY_THEMES]
    er_themes = [t for t in themes if t in EVENTREGISTRY_DISCOVERY_THEMES]
    newsapi_buckets = newsapi_buckets_for_themes(newsapi_themes)
    return SplitDiscoveryPlan(
        use_eventregistry=bool(er_themes),
        use_newsapi=bool(newsapi_themes),
        eventregistry_theme_keys=tuple(er_themes) if er_themes else None,
        newsapi_bucket_keys=tuple(newsapi_buckets) if newsapi_buckets else None,
    )


def _content_matches(blob: str, region: ThematicRegion) -> bool:
    lower = blob.lower()
    return any(kw in lower for kw in region.content_keywords)


def _country_for_candidate(candidate: ArticleCandidate) -> str:
    from src.coverage import infer_publisher_country

    return infer_publisher_country(source=candidate.source, url=candidate.url)


def article_matches_theme(candidate: ArticleCandidate, theme_id: str) -> bool:
    region = THEMATIC_REGIONS.get(theme_id)
    if not region:
        return False

    country = _country_for_candidate(candidate)
    if country and country in region.countries:
        return True

    search = (candidate.search_region or "").lower()
    if search == f"newsapi:{theme_id}" or search.startswith(f"newsapi:{theme_id}:"):
        return True
    if search.startswith("newsapi:eu") and theme_id == "europe":
        return True
    if search.startswith("newsapi:global_majority") and theme_id in (
        "asia",
        "africa",
        "latin_america",
        "middle_east",
    ):
        if country and country in region.countries:
            return True

    for code in region.ddgs_codes:
        if search == code or search.endswith(f":{code}"):
            return True

    blob = f"{candidate.headline} {candidate.snippet}"
    if _content_matches(blob, region):
        return True

    return False


def classify_thematic_region(candidate: ArticleCandidate) -> str:
    """Best-fit thematic label for display (Europe, Asia, etc.)."""
    for theme_id in UI_REGION_ORDER:
        if theme_id == "global":
            continue
        if article_matches_theme(candidate, theme_id):
            return THEMATIC_REGIONS[theme_id].label
    return ""


def filter_by_themes(
    candidates: list[ArticleCandidate],
    theme_ids: list[str],
) -> list[ArticleCandidate]:
    """Keep articles matching any selected thematic region."""
    theme_ids = normalize_region_selection(theme_ids)
    if not theme_ids:
        return candidates

    filtered: list[ArticleCandidate] = []
    for c in candidates:
        if any(article_matches_theme(c, tid) for tid in theme_ids):
            filtered.append(c)
    return filtered


def format_filter_summary(
    *,
    theme_ids: list[str],
    extra_keywords: str,
) -> str:
    parts: list[str] = []
    theme_ids = normalize_region_selection(theme_ids)
    if theme_ids:
        labels = [THEMATIC_REGIONS[t].label for t in theme_ids if t in THEMATIC_REGIONS]
        parts.append("Regions: " + ", ".join(labels))
    phrases = parse_keyword_phrases(extra_keywords)
    if phrases:
        parts.append("Keywords: " + ", ".join(phrases))
    return " · ".join(parts)


def build_config_query(extra_keywords: str, base: str = DEFAULT_QUERY) -> str:
    return build_search_query(base, extra_keywords)

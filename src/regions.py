"""News search regions for global coverage."""

from __future__ import annotations

import os

# DuckDuckGo region codes — worldwide + diverse economies
GLOBAL_NEWS_REGIONS: list[tuple[str, str]] = [
    ("wt-wt", "Worldwide"),
    ("us-en", "United States"),
    ("uk-en", "United Kingdom"),
    ("in-en", "India"),
    ("br-pt", "Brazil"),
    ("id-id", "Indonesia"),
    ("mx-es", "Mexico"),
    ("za-en", "South Africa"),
    ("pk-en", "Pakistan"),
    ("ph-en", "Philippines"),
    ("eg-ar", "Egypt"),
    ("ng-en", "Nigeria"),
    ("ke-en", "Kenya"),
    ("bd-en", "Bangladesh"),
    ("ar-es", "Argentina"),
    ("co-es", "Colombia"),
    ("tr-tr", "Turkey"),
    ("vn-en", "Vietnam"),
    ("th-en", "Thailand"),
    ("cn-zh", "China"),
    ("jp-jp", "Japan"),
    ("kr-kr", "South Korea"),
    ("de-de", "Germany"),
    ("fr-fr", "France"),
    ("es-es", "Spain"),
    ("it-it", "Italy"),
    ("nl-nl", "Netherlands"),
    ("pl-pl", "Poland"),
    ("au-en", "Australia"),
    ("ca-en", "Canada"),
    ("my-en", "Malaysia"),
    ("sg-en", "Singapore"),
    ("hk-en", "Hong Kong"),
    ("tw-en", "Taiwan"),
    ("ae-ar", "UAE"),
    ("sa-ar", "Saudi Arabia"),
    ("cl-es", "Chile"),
    ("pe-es", "Peru"),
    ("ru-ru", "Russia"),
    ("ua-uk", "Ukraine"),
    ("il-en", "Israel"),
    ("nz-en", "New Zealand"),
]

DEFAULT_REGION = "us-en"


def resolve_regions(
    *,
    global_coverage: bool = True,
    regions: list[str] | None = None,
) -> list[str]:
    """Return DDGS region codes to search."""
    if regions:
        return regions

    env = os.environ.get("DDGS_REGIONS", "").strip()
    if env:
        return [r.strip() for r in env.split(",") if r.strip()]

    if global_coverage:
        return [code for code, _ in GLOBAL_NEWS_REGIONS]

    return [DEFAULT_REGION]

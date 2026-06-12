"""Approximate coordinates for labor-impact map dots."""

from __future__ import annotations

import hashlib

# (latitude, longitude) for countries commonly seen in ER results.
COUNTRY_COORDS: dict[str, tuple[float, float]] = {
    "United States": (39.8, -98.5),
    "United Kingdom": (54.0, -2.5),
    "India": (22.0, 79.0),
    "China": (35.0, 103.0),
    "Japan": (36.2, 138.3),
    "Germany": (51.2, 10.5),
    "France": (46.2, 2.2),
    "Canada": (56.1, -106.3),
    "Australia": (-25.3, 133.8),
    "Brazil": (-14.2, -51.9),
    "Mexico": (23.6, -102.5),
    "South Africa": (-30.6, 22.9),
    "Nigeria": (9.1, 8.7),
    "Kenya": (-0.02, 37.9),
    "Egypt": (26.8, 30.8),
    "Israel": (31.0, 34.9),
    "Turkey": (39.0, 35.2),
    "Saudi Arabia": (23.9, 45.1),
    "United Arab Emirates": (23.4, 53.8),
    "Qatar": (25.3, 51.5),
    "Spain": (40.5, -3.7),
    "Italy": (41.9, 12.6),
    "Netherlands": (52.1, 5.3),
    "Switzerland": (46.8, 8.2),
    "Poland": (51.9, 19.1),
    "Sweden": (60.1, 18.6),
    "Norway": (60.5, 8.5),
    "Pakistan": (30.4, 69.3),
    "Bangladesh": (23.7, 90.4),
    "Philippines": (12.9, 121.8),
    "Thailand": (15.9, 100.9),
    "Vietnam": (14.1, 108.3),
    "Indonesia": (-2.5, 118.0),
    "Singapore": (1.35, 103.8),
    "South Korea": (36.5, 127.9),
    "Argentina": (-38.4, -63.6),
    "Colombia": (4.6, -74.1),
    "Chile": (-35.7, -71.5),
    "Peru": (-9.2, -75.0),
}

REGION_COORDS: dict[str, tuple[float, float]] = {
    "Asia": (30.0, 95.0),
    "Africa": (5.0, 20.0),
    "Latin America": (-15.0, -60.0),
    "Middle East": (28.0, 45.0),
    "Europe": (54.0, 15.0),
    "North America": (45.0, -100.0),
    "Global (creative / voice)": (20.0, 0.0),
    "Global (informal & platform work)": (10.0, 20.0),
    "Global (labor)": (25.0, 10.0),
    "Global (broad AI)": (30.0, -20.0),
    "Regional focus": (15.0, 50.0),
    "Global": (15.0, 0.0),
    "Unspecified": (0.0, 0.0),
}


def _jitter(url: str, scale: float = 4.0) -> tuple[float, float]:
    digest = hashlib.md5(url.encode()).hexdigest()
    a = int(digest[:8], 16) / 0xFFFFFFFF
    b = int(digest[8:16], 16) / 0xFFFFFFFF
    return (a - 0.5) * scale, (b - 0.5) * scale


def _base_coords(country: str, region: str) -> tuple[float, float]:
    country = (country or "").strip()
    region = (region or "").strip()
    if country in COUNTRY_COORDS:
        return COUNTRY_COORDS[country]
    if region in REGION_COORDS:
        return REGION_COORDS[region]
    for key, coords in COUNTRY_COORDS.items():
        if key.lower() in country.lower() or country.lower() in key.lower():
            return coords
    return REGION_COORDS.get(region, (10.0, 10.0))


def coords_for_us_state(state: str) -> tuple[float, float] | None:
    from src.us_states import coords_for_state

    return coords_for_state(state)


def coords_for_state_record(*, state: str, url: str) -> tuple[float, float] | None:
    """State centroid with per-story jitter so dots do not overlap."""
    base = coords_for_us_state(state)
    if not base:
        return None
    lat, lon = base
    dlat, dlon = _jitter(url)
    return round(lat + dlat, 4), round(lon + dlon, 4)


def coords_for_country(*, country: str, region: str) -> tuple[float, float]:
    """Stable centroid for a country (no per-story jitter)."""
    lat, lon = _base_coords(country, region)
    return round(lat, 4), round(lon, 4)


def coords_for_record(
    *,
    country: str,
    region: str,
    url: str,
) -> tuple[float, float]:
    """Return lat/lon with small jitter so incident dots do not fully overlap."""
    lat, lon = _base_coords(country, region)
    dlat, dlon = _jitter(url)
    return round(lat + dlat, 4), round(lon + dlon, 4)

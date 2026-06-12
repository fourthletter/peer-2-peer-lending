"""US state names, abbreviations, centroids, and text inference."""

from __future__ import annotations

import re

# (full name, abbrev, lat, lon) — approximate state centroids
US_STATES: tuple[tuple[str, str, float, float], ...] = (
    ("Alabama", "AL", 32.8, -86.8),
    ("Alaska", "AK", 64.2, -149.5),
    ("Arizona", "AZ", 34.3, -111.7),
    ("Arkansas", "AR", 34.8, -92.2),
    ("California", "CA", 36.8, -119.4),
    ("Colorado", "CO", 39.0, -105.5),
    ("Connecticut", "CT", 41.6, -72.7),
    ("Delaware", "DE", 39.0, -75.5),
    ("District of Columbia", "DC", 38.9, -77.0),
    ("Florida", "FL", 27.8, -81.7),
    ("Georgia", "GA", 33.0, -83.5),
    ("Hawaii", "HI", 21.1, -157.8),
    ("Idaho", "ID", 44.2, -114.5),
    ("Illinois", "IL", 40.0, -89.2),
    ("Indiana", "IN", 39.8, -86.3),
    ("Iowa", "IA", 42.0, -93.5),
    ("Kansas", "KS", 38.5, -98.4),
    ("Kentucky", "KY", 37.8, -85.7),
    ("Louisiana", "LA", 30.9, -92.0),
    ("Maine", "ME", 45.3, -69.4),
    ("Maryland", "MD", 39.0, -76.8),
    ("Massachusetts", "MA", 42.4, -71.4),
    ("Michigan", "MI", 44.3, -85.4),
    ("Minnesota", "MN", 46.3, -94.3),
    ("Mississippi", "MS", 32.7, -89.7),
    ("Missouri", "MO", 38.5, -92.4),
    ("Montana", "MT", 47.0, -109.6),
    ("Nebraska", "NE", 41.5, -99.8),
    ("Nevada", "NV", 39.3, -116.6),
    ("New Hampshire", "NH", 43.5, -71.6),
    ("New Jersey", "NJ", 40.1, -74.7),
    ("New Mexico", "NM", 34.5, -106.1),
    ("New York", "NY", 43.0, -75.5),
    ("North Carolina", "NC", 35.6, -79.4),
    ("North Dakota", "ND", 47.5, -100.5),
    ("Ohio", "OH", 40.4, -82.8),
    ("Oklahoma", "OK", 35.6, -97.5),
    ("Oregon", "OR", 44.0, -120.5),
    ("Pennsylvania", "PA", 40.9, -77.8),
    ("Rhode Island", "RI", 41.7, -71.5),
    ("South Carolina", "SC", 33.9, -80.9),
    ("South Dakota", "SD", 44.4, -100.2),
    ("Tennessee", "TN", 35.8, -86.3),
    ("Texas", "TX", 31.5, -99.3),
    ("Utah", "UT", 39.3, -111.7),
    ("Vermont", "VT", 44.0, -72.7),
    ("Virginia", "VA", 37.5, -78.7),
    ("Washington", "WA", 47.4, -120.5),
    ("West Virginia", "WV", 38.6, -80.6),
    ("Wisconsin", "WI", 44.3, -89.6),
    ("Wyoming", "WY", 43.0, -107.5),
)

STATE_BY_NAME: dict[str, tuple[str, float, float]] = {
    name: (abbrev, lat, lon) for name, abbrev, lat, lon in US_STATES
}
STATE_BY_ABBREV: dict[str, str] = {abbrev: name for name, abbrev, _, _ in US_STATES}

# Longer names first so "New York" matches before "York"
_NAME_PATTERNS: list[tuple[re.Pattern[str], str]] = []
for name, abbrev, _, _ in sorted(US_STATES, key=lambda s: -len(s[0])):
    _NAME_PATTERNS.append((re.compile(rf"\b{re.escape(name)}\b", re.I), name))
    _NAME_PATTERNS.append((re.compile(rf"\bin\s+{re.escape(name)}\b", re.I), name))
    _NAME_PATTERNS.append((re.compile(rf",\s*{re.escape(abbrev)}\b"), name))


def state_names() -> list[str]:
    return [name for name, _, _, _ in US_STATES]


def state_centroids_json() -> list[dict]:
    """For template JSON: name, lat, lon."""
    return [{"name": name, "lat": lat, "lon": lon} for name, _, lat, lon in US_STATES]


def coords_for_state(state: str) -> tuple[float, float] | None:
    entry = STATE_BY_NAME.get(state.strip())
    if not entry:
        return None
    _, lat, lon = entry
    return lat, lon


def infer_us_state(text: str) -> str:
    """Return full state name if found in headline/snippet text, else empty string."""
    if not text or not text.strip():
        return ""
    for pattern, name in _NAME_PATTERNS:
        if pattern.search(text):
            return name
    return ""

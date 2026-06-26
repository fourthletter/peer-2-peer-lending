"""Parse discovery metadata into labor-impact dimensions for visualization."""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from src.article import ArticleCandidate
from src.coverage import infer_publisher_country
from src.geo_diversity import geographic_bucket
from src.rank import RankedArticle
from src.thematic_regions import THEMATIC_REGIONS, classify_thematic_region

VIZ_MIN_DATE = date(2020, 1, 1)


def empty_impact_viz(*, year_label: str = "Jan 2020 – present") -> dict:
    return {
        "year_label": year_label,
        "date_from": VIZ_MIN_DATE.isoformat(),
        "date_to": date.today().isoformat(),
        "total": 0,
        "in_digest": 0,
        "by_region": [],
        "by_country": [],
        "by_job_type": [],
        "by_industry": [],
        "by_month": [],
        "by_year": [],
        "by_ai_incident": [],
        "map_points": [],
        "map_country_bubbles": [],
        "filter_options": {},
    }


def _viz_date_bounds(
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date]:
    """Clamp visualization window to Jan 2020 through today."""
    today = date.today()
    end = date_to or today
    start = date_from or VIZ_MIN_DATE
    start = max(start, VIZ_MIN_DATE)
    if start > end:
        start = VIZ_MIN_DATE
    return start, end


def _year_label(date_from: date, date_to: date) -> str:
    today = date.today()
    if date_from == VIZ_MIN_DATE and date_to >= today - timedelta(days=7):
        return "Jan 2020 – present"
    if date_from.year == date_to.year:
        return str(date_from.year)
    return f"{date_from.year}–{date_to.year}"

_BUCKET_LABELS = {
    "asia": "Asia",
    "africa": "Africa",
    "latin_america": "Latin America",
    "middle_east": "Middle East",
    "europe": "Europe",
    "north_america": "North America",
    "global_majority": "Global majority",
    "unknown": "Unspecified",
}

_JOB_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Voice & creative work", ("voice actor", "voice acting", "voiceover", "unauthorized ai voice", "plagiarism", "hollywood", "bollywood")),
    ("Garment & textile workers", ("garment", "textile", "sweatshop", "apparel", "fashion industry", "counterfeit fashion")),
    ("Platform & delivery work", ("uber", "lyft", "delivery driver", "delivery workers", "gig economy", "gig worker", "courier", "food delivery")),
    ("Warehouse & logistics", ("warehouse", "fulfillment center", "package delivery", "logistics worker")),
    ("Domestic & care work", ("nanny", "nannies", "maid", "maids", "domestic worker", "child care", "caregiver")),
    ("Street vending & informal trade", ("street vendor", "street vendors", "informal economy", "informal worker")),
    ("Technology & IT", ("software engineer", "tech worker", "it services", "it jobs", "programmer", "developer", "silicon valley")),
    ("Executive & white-collar", ("ceo", "executive", "white-collar", "white collar", "office worker", "entry-level", "entry level", "manager")),
    ("Manufacturing & industrial", ("factory", "manufacturing", "industrial worker", "assembly line")),
    ("Retail & service", ("retail worker", "cashier", "hospitality", "service worker", "call center")),
    ("Public sector & education", ("teacher", "professor", "public sector", "government worker", "civil servant")),
]

_AI_INCIDENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Job loss & layoffs", ("layoff", "layoffs", "job cut", "job loss", "fired", "redundan", "unemployment")),
    ("Hiring & labor demand", ("hiring", "job market", "employment growth", "wage", "recruit")),
    ("Automation & robotics", ("automation", "robot", "robotics", "self-driving", "autonomous")),
    ("Creative rights & voice", ("voice actor", "plagiarism", "copyright", "unauthorized ai voice", "creative")),
    ("Platform & gig work", ("uber", "gig economy", "delivery driver", "platform worker", "freelance platform")),
    ("Surveillance & monitoring", ("surveillance", "monitor", "facial recognition", "tracking workers")),
    ("Policy & regulation", ("regulation", "policy", "lawmakers", "legislation", "union", "strike", "collective bargaining")),
    ("Industry & sector change", ("industry", "sector", "manufacturing", "supply chain", "logistics", "retail")),
    ("Skills & reskilling", ("reskill", "upskill", "training program", "skills gap", "retrain")),
]

_INDUSTRY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Technology", ("technology", "tech ", "software", "semiconductor", "cloudflare", "microsoft", "google", "meta ", "openai")),
    ("Entertainment & media", ("entertainment", "film", "studio", "actor", "voice", "disney", "netflix", "gaming")),
    ("Finance & professional services", ("bank", "finance", "goldman", "consulting", "accounting", "ey ", "deloitte")),
    ("Healthcare", ("healthcare", "hospital", "clinical", "medical", "nursing")),
    ("Retail & apparel", ("retail", "apparel", "fashion", "garment", "clothing")),
    ("Logistics & transport", ("logistics", "shipping", "transport", "warehouse", "fedex", "ups ")),
    ("Domestic & personal services", ("domestic", "nanny", "maid", "cleaning")),
    ("Education", ("education", "university", "college", "school", "student")),
    ("Automotive & mobility", ("automotive", "tesla", "uber", "ride-hailing", "self-driving")),
]

_CONCEPT_JOB = {
    "voice acting": "Voice & creative work",
    "employment": "General labor & employment",
    "layoff": "General labor & employment",
    "labour economics": "General labor & employment",
    "automation": "General labor & employment",
    "textile": "Garment & textile workers",
    "clothing": "Garment & textile workers",
    "food delivery": "Platform & delivery work",
    "domestic worker": "Domestic & care work",
    "nanny": "Domestic & care work",
    "maid": "Domestic & care work",
}

_CONCEPT_INDUSTRY = {
    "artificial intelligence": "Technology",
    "entertainment": "Entertainment & media",
    "textile": "Retail & apparel",
    "clothing": "Retail & apparel",
    "uber": "Automotive & mobility",
    "amazon": "Retail & apparel",
}


@dataclass(frozen=True)
class LaborImpactRecord:
    headline: str
    url: str
    date: str
    region: str
    country: str
    job_type: str
    industry_type: str
    ai_incident_type: str
    lat: float = 0.0
    lon: float = 0.0
    country_lat: float = 0.0
    country_lon: float = 0.0
    us_state: str = ""
    in_digest: bool = False
    source: str = ""


def _blob(candidate: ArticleCandidate | RankedArticle | dict) -> str:
    if isinstance(candidate, dict):
        parts = [
            candidate.get("headline") or "",
            candidate.get("snippet") or "",
            candidate.get("text") or "",
            " ".join(candidate.get("concepts") or ()),
            " ".join(candidate.get("companies") or ()),
        ]
    else:
        parts = [
            candidate.headline,
            getattr(candidate, "snippet", "") or "",
            getattr(candidate, "text", "") or "",
            " ".join(getattr(candidate, "concepts", ()) or ()),
            " ".join(getattr(candidate, "companies", ()) or ()),
        ]
    return " ".join(parts).lower()


def _resolve_country(candidate: ArticleCandidate | RankedArticle | dict) -> str:
    if isinstance(candidate, dict):
        country = (
            candidate.get("location_country")
            or candidate.get("publisher_country")
            or ""
        ).strip()
        source = candidate.get("source") or ""
        url = candidate.get("url") or ""
    else:
        country = (
            getattr(candidate, "location_country", "") or ""
        ).strip() or (getattr(candidate, "publisher_country", "") or "").strip()
        source = candidate.source
        url = candidate.url
    if country and country not in ("International waters", "European Union", "Asia"):
        if "," in country:
            return country.split(",")[-1].strip()
        return country
    inferred = infer_publisher_country(source=source, url=url)
    return inferred or "Unknown"


def _region_from_candidate(candidate: ArticleCandidate | RankedArticle | dict) -> str:
    if isinstance(candidate, ArticleCandidate):
        thematic = candidate.thematic_region or classify_thematic_region(candidate)
        search = candidate.search_region or ""
        country = _resolve_country(candidate)
        pseudo = RankedArticle(
            headline=candidate.headline,
            url=candidate.url,
            score=0,
            reason="",
            text="",
            publisher_country=country,
            search_region=search,
            thematic_region=thematic,
        )
    elif isinstance(candidate, RankedArticle):
        thematic = candidate.thematic_region
        country = candidate.publisher_country or "Unknown"
        pseudo = candidate
    else:
        thematic = candidate.get("thematic_region") or ""
        country = _resolve_country(candidate)
        pseudo = RankedArticle(
            headline=candidate.get("headline") or "",
            url=candidate.get("url") or "",
            score=0,
            reason="",
            text="",
            publisher_country=country,
            search_region=candidate.get("search_region") or "",
            thematic_region=thematic,
        )

    if thematic:
        return thematic

    bucket = geographic_bucket(pseudo)
    if bucket in _BUCKET_LABELS and bucket != "global_majority":
        return _BUCKET_LABELS[bucket]

    for theme_id, region in THEMATIC_REGIONS.items():
        if theme_id == "global":
            continue
        if country in region.countries:
            return region.label

    if bucket == "global_majority":
        return "Global"

    search = (pseudo.search_region or "").lower()
    if search:
        return "Global"

    return "Unspecified"


def _match_rules(blob: str, rules: list[tuple[str, tuple[str, ...]]]) -> str | None:
    for label, phrases in rules:
        if any(p in blob for p in phrases):
            return label
    return None


def _job_type_from_concepts(concepts: tuple[str, ...] | list[str]) -> str | None:
    for raw in concepts:
        key = raw.lower()
        for needle, label in _CONCEPT_JOB.items():
            if needle in key:
                return label
    return None


def _industry_from_concepts(concepts: tuple[str, ...] | list[str]) -> str | None:
    for raw in concepts:
        key = raw.lower()
        for needle, label in _CONCEPT_INDUSTRY.items():
            if needle in key:
                return label
    return None


def parse_labor_impact(
    candidate: ArticleCandidate | RankedArticle | dict,
    *,
    in_digest: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
) -> LaborImpactRecord | None:
    """Extract labor-impact dimensions; returns None if outside the viz date window."""
    start, end = _viz_date_bounds(date_from, date_to)
    if isinstance(candidate, dict):
        published = candidate.get("published")
        headline = candidate.get("headline") or ""
        url = candidate.get("url") or ""
        concepts = tuple(candidate.get("concepts") or ())
        source = candidate.get("source") or ""
    else:
        published = candidate.published
        headline = candidate.headline
        url = candidate.url
        concepts = getattr(candidate, "concepts", ()) or ()
        source = candidate.source

    if not published:
        return None
    pub_day = published.date() if isinstance(published, datetime) else published
    if pub_day < start or pub_day > end:
        return None

    blob = _blob(candidate)
    search = ""
    if isinstance(candidate, ArticleCandidate):
        search = (candidate.search_region or "").lower()
    elif isinstance(candidate, RankedArticle):
        search = (candidate.search_region or "").lower()
    elif isinstance(candidate, dict):
        search = (candidate.get("search_region") or "").lower()

    job = _job_type_from_concepts(concepts) or _match_rules(blob, _JOB_RULES)
    if not job:
        if search.startswith("eventregistry:creative"):
            job = "Voice & creative work"
        elif search.startswith("eventregistry:workforce"):
            job = "Platform & delivery work"
        else:
            job = "General labor & employment"

    industry = _industry_from_concepts(concepts) or _match_rules(blob, _INDUSTRY_RULES)
    if not industry:
        industry = "Cross-sector"

    ai_incident = _match_rules(blob, _AI_INCIDENT_RULES)
    if not ai_incident:
        if search.startswith("eventregistry:creative"):
            ai_incident = "Creative rights & voice"
        elif "layoff" in blob or "job" in blob:
            ai_incident = "Job loss & layoffs"
        elif search.startswith("eventregistry:workforce"):
            ai_incident = "Platform & gig work"
        else:
            ai_incident = "Workforce & labor impact"

    region = _region_from_candidate(candidate)
    country = _resolve_country(candidate)
    from src.geo_coords import coords_for_country, coords_for_record, coords_for_state_record
    from src.us_states import infer_us_state

    us_state = ""
    if country == "United States":
        us_state = infer_us_state(blob)

    country_lat, country_lon = coords_for_country(country=country, region=region)
    state_coords = coords_for_state_record(state=us_state, url=url) if us_state else None
    if state_coords:
        lat, lon = state_coords
    else:
        lat, lon = coords_for_record(country=country, region=region, url=url)

    return LaborImpactRecord(
        headline=headline,
        url=url,
        date=published.strftime("%Y-%m-%d"),
        region=region,
        country=country,
        us_state=us_state,
        job_type=job,
        industry_type=industry,
        ai_incident_type=ai_incident,
        lat=lat,
        lon=lon,
        country_lat=country_lat,
        country_lon=country_lon,
        in_digest=in_digest,
        source=source,
    )


def _mode_label(records: list[LaborImpactRecord], field: str) -> str:
    counter = Counter(getattr(r, field) or "Unknown" for r in records)
    if not counter:
        return "Unknown"
    return counter.most_common(1)[0][0]


def _build_map_country_bubbles(records: list[LaborImpactRecord]) -> list[dict]:
    """Aggregate incidents by country for the map bubble layer."""
    by_country: dict[str, list[LaborImpactRecord]] = {}
    for r in records:
        if not r.country or r.country == "Unknown":
            continue
        if r.country_lat == 0.0 and r.country_lon == 0.0:
            continue
        by_country.setdefault(r.country, []).append(r)

    bubbles: list[dict] = []
    for country, group in sorted(by_country.items(), key=lambda x: -len(x[1])):
        dates = sorted(r.date for r in group if r.date)
        bubbles.append(
            {
                "country": country,
                "count": len(group),
                "lat": group[0].country_lat,
                "lon": group[0].country_lon,
                "region": _mode_label(group, "region"),
                "industry_type": _mode_label(group, "industry_type"),
                "ai_incident_type": _mode_label(group, "ai_incident_type"),
                "date_min": dates[0] if dates else "",
                "date_max": dates[-1] if dates else "",
            }
        )
    return bubbles


def _select_balanced_records(
    records: list[LaborImpactRecord],
    max_records: int,
) -> list[LaborImpactRecord]:
    """Prefer Africa, Latin America, and MENA when capping dashboard rows."""
    if os.environ.get("VIZ_GEO_BALANCE", "1") != "1" or len(records) <= max_records:
        return records[:max_records]

    from src.thematic_regions import viz_focus_region_labels

    focus_labels = set(viz_focus_region_labels())
    min_per = max(1, int(os.environ.get("VIZ_MIN_PER_FOCUS_REGION", "25")))

    by_region: dict[str, list[LaborImpactRecord]] = defaultdict(list)
    for r in records:
        by_region[r.region].append(r)

    selected: list[LaborImpactRecord] = []
    seen: set[str] = set()

    for label in focus_labels:
        for r in by_region.get(label, [])[:min_per]:
            if r.url in seen:
                continue
            seen.add(r.url)
            selected.append(r)

    rotation = list(focus_labels) + [
        label for label in sorted(by_region) if label not in focus_labels
    ]
    idx = 0
    while len(selected) < max_records and rotation:
        label = rotation[idx % len(rotation)]
        idx += 1
        pool = by_region.get(label, [])
        picked = False
        for r in pool:
            if r.url in seen:
                continue
            seen.add(r.url)
            selected.append(r)
            picked = True
            break
        if not picked and idx > len(records) * 2:
            break

    return selected[:max_records]


def build_impact_dataset(
    candidates: list[ArticleCandidate],
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    digest_urls: set[str] | None = None,
    max_records: int = 100,
) -> tuple[list[dict], dict]:
    """Parse articles in the viz date window and aggregate counts for charts."""
    date_from, date_to = _viz_date_bounds(date_from, date_to)
    year_label = _year_label(date_from, date_to)
    multi_year = date_to.year - date_from.year >= 1

    digest_urls = digest_urls or set()
    parsed: list[LaborImpactRecord] = []
    seen: set[str] = set()
    for c in candidates:
        if c.url in seen:
            continue
        row = parse_labor_impact(
            c,
            in_digest=c.url in digest_urls,
            date_from=date_from,
            date_to=date_to,
        )
        if row is None:
            continue
        seen.add(c.url)
        parsed.append(row)

    records = _select_balanced_records(parsed, max_records)

    def _top(counter: Counter[str], n: int = 12) -> list[dict]:
        return [{"label": k, "count": v} for k, v in counter.most_common(n)]

    by_region = Counter(r.region for r in records)
    by_country = Counter(r.country for r in records if r.country != "Unknown")
    by_job = Counter(r.job_type for r in records)
    by_industry = Counter(r.industry_type for r in records)
    by_ai = Counter(r.ai_incident_type for r in records)
    by_month = Counter(r.date[:7] for r in records if r.date)
    by_year = Counter(r.date[:4] for r in records if r.date)

    map_points = [
        {
            "lat": r.lat,
            "lon": r.lon,
            "country_lat": r.country_lat,
            "country_lon": r.country_lon,
            "region": r.region,
            "country": r.country,
            "us_state": r.us_state,
            "industry_type": r.industry_type,
            "ai_incident_type": r.ai_incident_type,
            "job_type": r.job_type,
            "date": r.date,
            "headline": r.headline,
            "url": r.url,
        }
        for r in records
    ]
    map_country_bubbles = _build_map_country_bubbles(records)

    viz = {
        "year_label": year_label,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "total": len(records),
        "in_digest": sum(1 for r in records if r.in_digest),
        "by_region": _top(by_region),
        "by_country": _top(by_country, 15),
        "by_job_type": _top(by_job),
        "by_industry": _top(by_industry),
        "by_ai_incident": _top(by_ai),
        "map_points": map_points,
        "map_country_bubbles": map_country_bubbles,
        "filter_options": {
            "regions": sorted({r.region for r in records}),
            "industries": sorted({r.industry_type for r in records}),
            "ai_incidents": sorted({r.ai_incident_type for r in records}),
            "job_types": sorted({r.job_type for r in records}),
            "us_states": sorted({r.us_state for r in records if r.us_state}),
        },
        "by_month": [
            {"label": m, "count": by_month[m]}
            for m in sorted(by_month)
        ],
        "by_year": [
            {"label": y, "count": by_year[y]}
            for y in sorted(by_year)
        ],
        "timeline_mode": "year" if multi_year else "month",
    }
    return [asdict(r) for r in records], viz

from datetime import date, datetime, timezone

from src.article import ArticleCandidate
from src.labor_impact_parse import build_impact_dataset, parse_labor_impact


def _candidate(headline: str, url: str, snippet: str = "") -> ArticleCandidate:
    return ArticleCandidate(
        headline=headline,
        url=url,
        published=datetime(2024, 5, 1, tzinfo=timezone.utc),
        source="Example",
        snippet=snippet,
    )


def test_parse_labor_impact_assigns_region_from_country():
    candidate = ArticleCandidate(
        headline="Kenya garment workers face AI automation in factories",
        url="https://example.com/kenya-ai",
        published=datetime(2024, 5, 1, tzinfo=timezone.utc),
        source="Example",
        snippet="Automation threatens textile jobs in Nairobi.",
        location_country="Kenya",
        thematic_region="Africa",
    )
    record = parse_labor_impact(
        candidate,
        date_from=date(2020, 1, 1),
        date_to=date.today(),
    )
    assert record is not None
    assert record.country == "Kenya"
    assert record.region == "Africa"
    assert record.ai_incident_type


def test_relevance_gate_drops_generic_ai_news():
    candidate = _candidate(
        "New AI model can generate videos from text",
        "https://example.com/ai-video",
        "The startup released an impressive generative model.",
    )
    record = parse_labor_impact(
        candidate, date_from=date(2020, 1, 1), date_to=date.today()
    )
    assert record is None


def test_word_boundary_rules_avoid_substring_misclassification():
    candidate = _candidate(
        "Advocacy groups say AI hiring tools discriminate against workers",
        "https://example.com/groups-ai",
        "Civil society groups call for oversight of AI in employment.",
    )
    record = parse_labor_impact(
        candidate, date_from=date(2020, 1, 1), date_to=date.today()
    )
    assert record is not None
    # "groups" must not match the "ups" logistics keyword.
    assert record.industry_type != "Logistics & transport"


def test_build_impact_dataset_dedupes_syndicated_headlines():
    headline = "AI automation to cut thousands of warehouse jobs this year"
    candidates = [
        _candidate(headline, "https://outlet-a.com/story"),
        _candidate(headline, "https://outlet-b.com/syndicated-copy"),
        _candidate(
            "Union wins protections against AI surveillance of workers",
            "https://outlet-c.com/other-story",
        ),
    ]
    records, viz = build_impact_dataset(
        candidates, date_from=date(2020, 1, 1), date_to=date.today()
    )
    assert len(records) == 2
    assert viz["total"] == 2

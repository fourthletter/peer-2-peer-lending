from datetime import date, datetime, timezone

from src.article import ArticleCandidate
from src.labor_impact_parse import parse_labor_impact


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

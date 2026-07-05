from datetime import date, datetime, timezone

from src.parse_dates import in_date_range, parse_published


def test_in_date_range_excludes_undated():
    assert in_date_range(None, date(2024, 1, 1), date(2024, 12, 31)) is False


def test_in_date_range_includes_dated():
    published = datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert in_date_range(published, date(2024, 1, 1), date(2024, 12, 31)) is True


def test_in_date_range_excludes_before_start():
    published = datetime(2019, 12, 31, tzinfo=timezone.utc)
    assert in_date_range(published, date(2020, 1, 1), date(2024, 12, 31)) is False


def test_parse_published_iso():
    dt = parse_published("2024-03-15T10:00:00Z")
    assert dt is not None
    assert dt.year == 2024

from datetime import date

from src.discover import ddgs_effective_range, timelimit_for_range


def test_ddgs_effective_range_caps_long_spans():
    start, end = ddgs_effective_range(date(2020, 1, 1), date(2024, 6, 1))
    assert end == date(2024, 6, 1)
    assert (end - start).days <= 31


def test_ddgs_effective_range_short_span_unchanged():
    start, end = ddgs_effective_range(date(2024, 5, 1), date(2024, 5, 20))
    assert start == date(2024, 5, 1)
    assert end == date(2024, 5, 20)


def test_timelimit_for_range_week():
    assert timelimit_for_range(date(2024, 5, 1), date(2024, 5, 5)) == "w"

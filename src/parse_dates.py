"""Parse publication dates from assorted feed formats."""

from __future__ import annotations

from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime


def parse_published(raw: str | int | float | None) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    text = str(raw).strip()
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(text[:10], fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def in_date_range(
    published: datetime | None,
    date_from: date | None,
    date_to: date | None,
) -> bool:
    if published is None:
        return True
    pub_date = published.date()
    if date_from and pub_date < date_from:
        return False
    if date_to and pub_date > date_to:
        return False
    return True


def format_published_date(published: datetime | None) -> str:
    """Human-readable publication date for digests."""
    if published is None:
        return ""
    dt = published
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%b %d, %Y")

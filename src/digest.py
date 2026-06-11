"""Format weekly digest as plain text and HTML."""

from __future__ import annotations

from datetime import datetime, timezone
import html

from src.coverage import discovery_region_label, format_publisher_line
from src.parse_dates import format_published_date
from src.summarize import DigestArticle


def digest_date() -> str:
    return datetime.now(timezone.utc).strftime("%b %d, %Y")


def subject_line(date_range: str | None = None) -> str:
    if date_range:
        return f"AI & Labor Digest — {date_range}"
    return f"AI & Labor Weekly — {digest_date()}"


def format_plain(
    articles: list[DigestArticle],
    note: str = "",
    *,
    title_suffix: str | None = None,
    coverage_label: str = "",
) -> str:
    heading = f"Weekly AI & Labor Market Digest — {title_suffix or digest_date()}"
    lines = [heading, ""]
    if coverage_label:
        lines.append(f"Coverage: {coverage_label}")
        lines.append("")

    if not articles:
        lines.append("No qualifying articles were found this week.")
    else:
        for i, a in enumerate(articles, 1):
            lines.append(f"{i}. {a.headline}")
            date_label = format_published_date(a.published)
            if date_label:
                lines.append(f"   {date_label}")
            publisher_line = format_publisher_line(
                source=a.source,
                publisher_country=a.publisher_country,
            )
            if publisher_line:
                lines.append(f"   {publisher_line}")
            region_label = discovery_region_label(a.search_region)
            if region_label:
                lines.append(f"   Discovered via: {region_label}")
            if a.thematic_region:
                lines.append(f"   Region / theme: {a.thematic_region}")
            lines.append(f"   {a.url}")
            lines.append(f"   {a.summary}")
            lines.append("")

    if note:
        lines.append(note)

    return "\n".join(lines).strip()


def format_html(
    articles: list[DigestArticle],
    note: str = "",
    *,
    title_suffix: str | None = None,
    coverage_label: str = "",
) -> str:
    heading = f"Weekly AI &amp; Labor Market Digest — {html.escape(title_suffix or digest_date())}"
    parts = ["<html><body>", f"<h1>{heading}</h1>"]
    if coverage_label:
        parts.append(
            f"<p><strong>Coverage:</strong> {html.escape(coverage_label)}</p>"
        )

    if not articles:
        parts.append("<p>No qualifying articles were found this week.</p>")
    else:
        parts.append("<ol>")
        for a in articles:
            parts.append("<li style='margin-bottom:1.5em'>")
            parts.append(f"<strong>{html.escape(a.headline)}</strong><br>")
            date_label = format_published_date(a.published)
            if date_label:
                parts.append(
                    f"<span style='color:#555'>{html.escape(date_label)}</span><br>"
                )
            publisher_line = format_publisher_line(
                source=a.source,
                publisher_country=a.publisher_country,
            )
            if publisher_line:
                parts.append(
                    f"<span style='color:#555'>{html.escape(publisher_line)}</span><br>"
                )
            region_label = discovery_region_label(a.search_region)
            if region_label:
                parts.append(
                    f"<span style='color:#555'>Discovered via: "
                    f"{html.escape(region_label)}</span><br>"
                )
            if a.thematic_region:
                parts.append(
                    f"<span style='color:#555'>Region / theme: "
                    f"{html.escape(a.thematic_region)}</span><br>"
                )
            parts.append(
                f'<a href="{html.escape(a.url)}">{html.escape(a.url)}</a><br>'
            )
            parts.append(f"<p>{html.escape(a.summary)}</p>")
            parts.append("</li>")
        parts.append("</ol>")

    if note:
        parts.append(f"<p><em>{html.escape(note)}</em></p>")

    parts.append("</body></html>")
    return "\n".join(parts)

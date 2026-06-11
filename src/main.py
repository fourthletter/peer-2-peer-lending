"""Weekly AI & Labor Market news digest agent (CLI)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

from src.config import (
    DEFAULT_ARTICLE_COUNT,
    DEFAULT_LOOKBACK_DAYS,
    MAX_ARTICLE_COUNT,
    MIN_ARTICLE_COUNT,
    DigestConfig,
)
from src.pipeline import build_digest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Weekly AI & Labor Market news digest agent"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print digest without sending email or saving history",
    )
    group.add_argument(
        "--send",
        action="store_true",
        help="Send digest via SMTP and update sent URL history",
    )
    parser.add_argument(
        "--from-date",
        type=_parse_date,
        help="Start date for articles (YYYY-MM-DD). Default: 7 days ago",
    )
    parser.add_argument(
        "--to-date",
        type=_parse_date,
        help="End date for articles (YYYY-MM-DD). Default: today",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_ARTICLE_COUNT,
        metavar="N",
        help=f"Number of articles in digest ({MIN_ARTICLE_COUNT}-{MAX_ARTICLE_COUNT})",
    )
    parser.add_argument(
        "--us-only",
        action="store_true",
        help="Search US news region only (disable global multi-region discovery)",
    )
    parser.add_argument(
        "--newsapi-only",
        action="store_true",
        help="Use NewsAPI.org only (fast; requires NEWS_API_KEY in .env)",
    )
    args = parser.parse_args()

    load_dotenv()

    today = date.today()
    newsapi_only = args.newsapi_only or (
        os.environ.get("DISCOVERY_SOURCE", "").strip().lower() == "newsapi"
    )
    config = DigestConfig(
        date_from=args.from_date
        or (today - timedelta(days=DEFAULT_LOOKBACK_DAYS)),
        date_to=args.to_date or today,
        article_count=args.count,
        global_coverage=not args.us_only and not newsapi_only,
        newsapi_only=newsapi_only,
    )

    try:
        result = build_digest(
            config,
            dry_run=args.dry_run,
            send_email=args.send,
        )
    except Exception:
        logger.exception("Digest run failed")
        sys.exit(1)

    print(result.plain)
    print("\n" + "=" * 60 + "\n")
    sys.exit(0)


if __name__ == "__main__":
    main()

"""Web UI for configuring and running the news digest."""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, flash, jsonify, redirect, render_template, request, session, url_for

from src.config import (
    DEFAULT_ARTICLE_COUNT,
    MAX_ARTICLE_COUNT,
    MIN_ARTICLE_COUNT,
    DigestConfig,
)
from src.coverage import discovery_region_label
from src.discover import DEFAULT_QUERY
from src.impact_viz import ImpactVizResult, build_labor_impact_viz
from src.labor_impact_parse import VIZ_MIN_DATE
from src.viz_cache import load_payload_cache, save_payload_cache
from src.narrative_cases import NARRATIVE_CASES
from src.pipeline import DigestResult, build_digest
from src.thematic_regions import THEMATIC_REGIONS, UI_REGION_ORDER
from src.us_states import state_centroids_json, state_names

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_SECRET_KEY = "news-agent-dev-key-change-me"

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", DEFAULT_SECRET_KEY)
app.jinja_env.globals["discovery_region_label"] = discovery_region_label

DEFAULT_MTC_URL = "https://morethancode.org"


def site_url() -> str:
    return os.environ.get("SITE_URL", DEFAULT_MTC_URL).rstrip("/")


def static_site() -> bool:
    return os.environ.get("STATIC_BUILD", "").lower() in ("1", "true", "yes")


app.jinja_env.globals["site_url"] = site_url
app.jinja_env.globals["static_site"] = static_site


def _parse_form_date(name: str, default: date) -> date:
    raw = request.form.get(name, "").strip()
    if not raw:
        return default
    return datetime.strptime(raw, "%Y-%m-%d").date()


RANGE_PRESETS = ("week", "month", "year", "ytd", "since2020")


def _subtract_months(d: date, months: int) -> date:
    month_index = (d.year * 12 + (d.month - 1)) - months
    year, month = divmod(month_index, 12)
    month += 1
    # Clamp day to the last valid day of the target month.
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_day = (next_month_first - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


def _range_from_preset(preset: str, today: date) -> tuple[date, date] | None:
    """Compute (start, end) for a quick-range preset, or None for custom dates."""
    preset = (preset or "").strip().lower()
    if preset == "week":
        return today - timedelta(days=7), today
    if preset == "month":
        return _subtract_months(today, 1), today
    if preset == "year":
        try:
            start = today.replace(year=today.year - 1)
        except ValueError:
            start = today - timedelta(days=365)
        return start, today
    if preset == "ytd":
        return date(today.year, 1, 1), today
    if preset == "since2020":
        return date(2020, 1, 1), today
    return None


def _discovery_source() -> str:
    return os.environ.get("DISCOVERY_SOURCE", "hybrid").strip().lower()


def _newsapi_only_from_env() -> bool:
    return _discovery_source() == "newsapi"


def _api_discovery_from_env() -> bool:
    """Structured API discovery (NewsAPI and/or Event Registry), no DDGS/RSS."""
    return _discovery_source() in {
        "api",
        "apis",
        "newsapi",
        "eventregistry",
        "split",
    }


def _config_from_form() -> DigestConfig:
    defaults = DigestConfig.default_weekly()
    article_count = int(request.form.get("article_count", DEFAULT_ARTICLE_COUNT))
    newsapi_only = _newsapi_only_from_env()
    api_discovery = _api_discovery_from_env()
    geographic_regions = tuple(request.form.getlist("geographic_regions"))
    extra_keywords = request.form.get("extra_keywords", "").strip()

    preset_range = _range_from_preset(request.form.get("range_preset", ""), date.today())
    if preset_range is not None:
        date_from, date_to = preset_range
    else:
        date_from = _parse_form_date("date_from", defaults.date_from)
        date_to = _parse_form_date("date_to", defaults.date_to)

    return DigestConfig(
        date_from=date_from,
        date_to=date_to,
        article_count=article_count,
        query=DEFAULT_QUERY,
        skip_dedup=True,
        global_coverage=not (newsapi_only or api_discovery),
        newsapi_only=newsapi_only,
        extra_keywords=extra_keywords,
        geographic_regions=geographic_regions,
    )


def _viz_cache_dates() -> tuple[date, date] | None:
    """Date range stored with the last successful viz refresh."""
    payload = load_payload_cache()
    if not payload:
        return None
    try:
        raw_from = payload.get("date_from")
        raw_to = payload.get("date_to")
        if raw_from and raw_to:
            return (
                datetime.strptime(raw_from, "%Y-%m-%d").date(),
                datetime.strptime(raw_to, "%Y-%m-%d").date(),
            )
    except ValueError:
        return None
    return None


def _viz_from_cache() -> ImpactVizResult | None:
    """Load viz from disk — Flask session cookies cannot hold full chart payloads."""
    payload = load_payload_cache()
    if not payload:
        return None
    return ImpactVizResult(
        records=payload.get("records") or [],
        viz=payload.get("viz") or {},
        discovered=int(payload.get("discovered") or 0),
        filter_summary=payload.get("filter_summary") or "",
    )


def _serialize_digest(result: DigestResult) -> dict:
    articles = []
    for a in result.articles:
        articles.append(
            {
                "headline": a.headline,
                "url": a.url,
                "summary": a.summary,
                "published": a.published.isoformat() if a.published else "",
                "source": a.source,
                "publisher_country": a.publisher_country,
                "search_region": a.search_region,
                "thematic_region": a.thematic_region,
                "concepts": list(a.concepts),
                "companies": list(a.companies),
            }
        )
    return {
        "articles": articles,
        "discovered": result.discovered,
        "new_candidates": result.new_candidates,
        "ranked_count": result.ranked_count,
        "note": result.note,
        "plain": result.plain,
        "coverage_label": result.coverage_label,
        "filter_summary": result.filter_summary,
        "search_query": result.search_query,
    }


def _digest_from_session() -> SimpleNamespace | None:
    payload = session.get("digest_payload")
    if not payload:
        return None
    articles = []
    for raw in payload.get("articles") or []:
        published = None
        if raw.get("published"):
            try:
                published = datetime.fromisoformat(raw["published"])
            except ValueError:
                published = None
        articles.append(
            SimpleNamespace(
                headline=raw.get("headline") or "",
                url=raw.get("url") or "",
                summary=raw.get("summary") or "",
                published=published,
                source=raw.get("source") or "",
                publisher_country=raw.get("publisher_country") or "",
                search_region=raw.get("search_region") or "",
                thematic_region=raw.get("thematic_region") or "",
                concepts=tuple(raw.get("concepts") or ()),
                companies=tuple(raw.get("companies") or ()),
            )
        )
    return SimpleNamespace(
        articles=articles,
        discovered=payload.get("discovered", 0),
        new_candidates=payload.get("new_candidates", 0),
        ranked_count=payload.get("ranked_count", 0),
        note=payload.get("note") or "",
        plain=payload.get("plain") or "",
        coverage_label=payload.get("coverage_label") or "",
        filter_summary=payload.get("filter_summary") or "",
        search_query=payload.get("search_query") or "",
    )


def _store_digest_session(result: DigestResult) -> None:
    session["digest_payload"] = _serialize_digest(result)
    session["digest_urls"] = [a.url for a in result.articles]


def _store_viz_cache(
    viz_result: ImpactVizResult,
    *,
    date_from: date,
    date_to: date,
) -> None:
    save_payload_cache(
        {
            "records": viz_result.records,
            "viz": viz_result.viz,
            "discovered": viz_result.discovered,
            "filter_summary": viz_result.filter_summary,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        }
    )


def _template_context(
    *,
    result=None,
    viz_result=None,
    form_values=None,
    active_tab: str = "dashboard",
):
    defaults = DigestConfig.default_weekly()
    thematic_options = [
        (tid, THEMATIC_REGIONS[tid].label)
        for tid in UI_REGION_ORDER
        if tid in THEMATIC_REGIONS
    ]
    # Empty selection means Global; show the Global checkbox as checked.
    selected_regions = list(defaults.geographic_regions) or ["global"]
    extra_keywords = ""
    date_from = defaults.date_from
    date_to = defaults.date_to
    if form_values is not None:
        selected_regions = list(form_values.getlist("geographic_regions"))
        if not selected_regions:
            selected_regions = list(defaults.geographic_regions) or ["global"]
        extra_keywords = form_values.get("extra_keywords", "")
        preset_range = _range_from_preset(
            form_values.get("range_preset", ""), date.today()
        )
        if preset_range is not None:
            date_from, date_to = preset_range
        else:
            date_from = _parse_form_date("date_from", defaults.date_from)
            date_to = _parse_form_date("date_to", defaults.date_to)
    return {
        "active_tab": active_tab,
        "defaults": defaults,
        "min_count": MIN_ARTICLE_COUNT,
        "max_count": MAX_ARTICLE_COUNT,
        "result": result,
        "viz_result": viz_result,
        "form_values": form_values,
        "thematic_options": thematic_options,
        "region_theme_labels": {
            tid: THEMATIC_REGIONS[tid].label
            for tid in UI_REGION_ORDER
            if tid in THEMATIC_REGIONS
        },
        "selected_regions": selected_regions,
        "extra_keywords": extra_keywords,
        "date_from": date_from,
        "date_to": date_to,
        "current_year": date.today().year,
    }


def _startup_viz_config() -> DigestConfig:
    """Default dashboard window: Jan 2020 through today (includes yearly ER backfill)."""
    from src.thematic_regions import default_geographic_regions

    today = date.today()
    return DigestConfig(
        date_from=VIZ_MIN_DATE,
        date_to=today,
        article_count=DEFAULT_ARTICLE_COUNT,
        skip_dedup=True,
        global_coverage=not _api_discovery_from_env(),
        newsapi_only=False,
        geographic_regions=default_geographic_regions(),
    )


@app.route("/narratives", methods=["GET"])
def narratives():
    return render_template(
        "narratives.html",
        active_tab="narratives",
        narrative_cases=NARRATIVE_CASES,
    )


@app.route("/methodology", methods=["GET"])
def methodology():
    return render_template("methodology.html", active_tab="methodology")


def _viz_page_context(
    *,
    form_values=None,
    viz_result: ImpactVizResult | None = None,
) -> dict:
    startup_cfg = _startup_viz_config()
    if viz_result is None:
        viz_result = _viz_from_cache()
        if not viz_result and os.environ.get("VIZ_LOAD_ON_STARTUP", "0") == "1":
            try:
                viz_result = build_labor_impact_viz(startup_cfg)
                _store_viz_cache(
                    viz_result,
                    date_from=startup_cfg.date_from,
                    date_to=startup_cfg.date_to,
                )
            except (ValueError, RuntimeError) as exc:
                flash(f"Could not load default charts: {exc}", "error")
            except Exception:
                logger.exception("Startup chart load failed")
                flash("Could not load default charts. Use Refresh data to try again.", "error")

    ctx = _template_context(
        active_tab="incidents",
        viz_result=viz_result,
        result=_digest_from_session(),
        form_values=form_values,
    )
    cached_dates = _viz_cache_dates()
    if cached_dates:
        ctx["date_from"], ctx["date_to"] = cached_dates
    else:
        ctx["date_from"] = startup_cfg.date_from
        ctx["date_to"] = startup_cfg.date_to
    ctx["us_state_names"] = state_names()
    ctx["us_state_centroids"] = state_centroids_json()
    return ctx


@app.route("/projects", methods=["GET"])
@app.route("/health", methods=["GET"])
def projects():
    return jsonify({"ok": True, "runtime": "flask"})


def _is_local_request() -> bool:
    host = (request.host or "").split(":")[0].lower()
    return host in ("127.0.0.1", "localhost", "::1")


@app.route("/", methods=["GET"])
def index():
    if _is_local_request() or static_site():
        return redirect(url_for("incidents"))
    return redirect(f"{site_url()}/incidents")


@app.route("/incidents", methods=["GET"])
def incidents():
    return render_template("viz.html", **_viz_page_context())


@app.route("/news", methods=["GET"])
def news():
    defaults = DigestConfig.default_weekly()
    ctx = _template_context(
        active_tab="news",
        result=_digest_from_session(),
    )
    ctx["date_from"] = defaults.date_from
    ctx["date_to"] = defaults.date_to
    return render_template("digest.html", **ctx)


@app.route("/preview", methods=["POST"])
def preview():
    try:
        config = _config_from_form()
        result = build_digest(config, dry_run=True)
    except (ValueError, RuntimeError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("news"))
    except Exception:
        logger.exception("Digest preview failed")
        flash("Preview failed. Check logs and try again.", "error")
        return redirect(url_for("news"))

    _store_digest_session(result)
    ctx = _template_context(
        active_tab="news",
        result=result,
        viz_result=_viz_from_cache(),
        form_values=request.form,
    )
    return render_template("digest.html", **ctx)


@app.route("/viz", methods=["POST"])
def load_viz():
    """Load labor-impact charts only (no digest ranking or summaries)."""
    try:
        config = _config_from_form()
        digest_urls = set(session.get("digest_urls") or [])
        viz_result = build_labor_impact_viz(config, digest_urls=digest_urls)
        _store_viz_cache(
            viz_result,
            date_from=config.date_from,
            date_to=config.date_to,
        )
        flash(
            f"Data refreshed: {viz_result.viz.get('total', 0)} incidents parsed "
            f"from {viz_result.discovered} discovered.",
            "success",
        )
    except (ValueError, RuntimeError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("incidents"))

    ctx = _viz_page_context(form_values=request.form, viz_result=viz_result)
    return render_template("viz.html", **ctx)


@app.route("/export", methods=["POST"])
def export_csv():
    """Download digest rows from the last preview (no re-run)."""
    result = _digest_from_session()
    if not result or not result.articles:
        flash("No preview to export. Run Preview first.", "error")
        return redirect(url_for("news"))

    try:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["title", "date", "summary", "concepts", "companies", "country", "url"])
        for article in result.articles:
            day = article.published.strftime("%Y-%m-%d") if article.published else ""
            writer.writerow(
                [
                    article.headline,
                    day,
                    article.summary,
                    ", ".join(article.concepts),
                    ", ".join(article.companies),
                    article.publisher_country,
                    article.url,
                ]
            )
        filename = f"aim-digest-{date.today().isoformat()}.csv"
        return Response(
            buf.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception:
        logger.exception("CSV export failed")
        flash("Export failed. Try previewing again.", "error")
        return redirect(url_for("news"))


DEFAULT_PORT = 5050


def main() -> None:
    port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    if app.secret_key == DEFAULT_SECRET_KEY:
        logger.warning("Using default FLASK_SECRET_KEY — set a unique value in production")
    site_url_val = site_url()
    print(f"MoreThanCode AI & Labor Monitor: {site_url_val}")
    print(f"  Labor Impact Dashboard: {site_url_val}/incidents")
    print(f"  News aggregator:          {site_url_val}/news")
    app.run(host="127.0.0.1", port=port, debug=debug)


if __name__ == "__main__":
    main()

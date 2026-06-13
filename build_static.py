"""Export the Flask UI as static HTML for GitHub Pages."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("STATIC_BUILD", "1")
os.environ.setdefault("VIZ_LOAD_ON_STARTUP", "0")
os.environ.setdefault("SITE_URL", "https://morethancode.org")

from flask_frozen import Freezer

from src.web import app

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

app.url_map.strict_slashes = False
app.config["FREEZER_DESTINATION"] = str(DIST)
app.config["FREEZER_RELATIVE_URLS"] = True
app.config["FREEZER_REMOVE_EXTRA_FILES"] = False
app.config["FREEZER_IGNORE_MIMETYPE_WARNINGS"] = True

freezer = Freezer(app)


def _maybe_warm_viz_cache() -> None:
    if not os.environ.get("EVENTREGISTRY_API_KEY", "").strip():
        print("Skipping viz preload (EVENTREGISTRY_API_KEY not set)")
        return
    os.environ.setdefault("VIZ_CACHE_DIR", str(ROOT / ".viz_cache"))
    try:
        from src.impact_viz import build_labor_impact_viz
        from src.web import _startup_viz_config, _store_viz_cache

        cfg = _startup_viz_config()
        print("Preloading Labor Impact Dashboard data for static export…")
        result = build_labor_impact_viz(cfg)
        _store_viz_cache(result, date_from=cfg.date_from, date_to=cfg.date_to)
        total = (result.viz or {}).get("total", 0)
        print(f"Cached {total} incidents for static export")
    except Exception as exc:
        print(f"Warning: viz preload failed ({exc}); exporting empty dashboard")


@freezer.register_generator
def narratives():
    yield "/narratives"


@freezer.register_generator
def incidents():
    yield "/incidents"


@freezer.register_generator
def news():
    yield "/news"


@freezer.register_generator
def index():
    yield "/"


if __name__ == "__main__":
    if os.environ.get("WARM_VIZ_CACHE", "1") == "1":
        _maybe_warm_viz_cache()
    freezer.freeze()
    for name in ("incidents", "news", "narratives"):
        src = DIST / name
        if src.is_file():
            tmp = DIST / f"_{name}.html"
            src.rename(tmp)
            page_dir = DIST / name
            page_dir.mkdir(exist_ok=True)
            tmp.rename(page_dir / "index.html")
    for stray in (DIST / "health", DIST / "projects"):
        if stray.is_file():
            stray.unlink()
    index_redirect = DIST / "index.html"
    if not index_redirect.is_file():
        incidents_index = DIST / "incidents" / "index.html"
        if incidents_index.is_file():
            index_redirect.write_text(
                '<!DOCTYPE html><html><head>'
                '<meta http-equiv="refresh" content="0; url=incidents/">'
                '<link rel="canonical" href="incidents/">'
                '</head><body><p><a href="incidents/">Labor Impact Dashboard</a></p></body></html>',
                encoding="utf-8",
            )
    (DIST / "health.json").write_text('{"ok":true,"runtime":"static"}', encoding="utf-8")
    print(f"Static site written to {DIST}")

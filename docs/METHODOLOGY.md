# Labor Impact Dashboard — methodology

This document describes how the [MoreThanCode AI & Labor Monitor](https://morethancode.org/incidents) discovers, classifies, and displays **labor-impact incidents** on the public dashboard.

## Purpose

The dashboard tracks **reported news about artificial intelligence and its effects on work**: layoffs and hiring shifts, automation, platform and gig labor, creative rights, unions and policy, and sector-level workforce change. It is a **monitoring and exploration tool**, not a complete census of global labor events.

Each row in **Explore articles** is one news article that matched discovery criteria and was parsed into structured fields for maps and charts.

## Timespan

| Setting | Value |
|---------|--------|
| **Default window** | **January 1, 2020** through **today** |
| **Minimum date** | Hard floor at `2020-01-01` (`VIZ_MIN_DATE` in code) |
| **User adjustment** | On the dashboard, choose start/end dates or presets (last week, last month, 2026 YTD, Jan 2020 – now) |
| **Local refresh** | Click **Refresh data** to re-query sources for the selected range (1–2 minutes for full history) |
| **Production (morethancode.org)** | Data is **embedded at build time** when GitHub Pages deploys; the static site does not live-query APIs. Re-deploy or run locally to update. |

For ranges spanning multiple years, discovery uses a **per-year cache** (`.viz_cache/years/`) plus a **recent-year live pull** so long histories stay tractable.

## What counts as an incident

An **incident** is a single **news article** (URL) that:

1. Was returned by at least one enabled discovery source (below).
2. Has a **parseable publication date** inside the selected date window.
3. Survives **deduplication** by canonical URL (first source to report a URL wins).

There is **no manual editorial gate** on the dashboard pipeline. Classification uses **headlines, snippets, Event Registry concepts, and rule-based keyword matching**—not human review.

The dashboard does **not** count:

- Social posts unless they appear in a supplemented feed (e.g. Reddit discovery in supplements).
- Academic papers or grey literature unless indexed by a news source.
- Duplicate URLs across sources (one row per URL).

## Data sources

Discovery runs in [`src/impact_viz.py`](../src/impact_viz.py) and merges batches in **round-robin order** so regional results are not drowned out by US/UK-heavy global pulls.

### Primary: Event Registry (newsapi.ai)

Requires `EVENTREGISTRY_API_KEY`.

- **Concept queries**: articles tagged with *Artificial intelligence* plus labor-related concepts (employment, layoffs, workforce, automation, gig economy, etc.).
- **Per-theme regional pulls**: separate queries filtered by publisher country for focus regions (default: Africa, Latin America, Middle East).
- **Yearly history**: one labor query per calendar year (plus optional per-theme supplements per year).
- **Live window**: streamlined labor query for the recent year (+ regional supplement when enabled).
- **Broad export mode** (`VIZ_ER_BROAD=1`): additional `ai_export` merge (~65% labor + ~35% broad AI) for wider coverage.

Event Registry draws on **150,000+ global sources** in many languages; dashboard queries default to **English** (`lang: eng`).

### Supplement: NewsAPI.org

Used when `NEWS_API_KEY` is set. Dashboard buckets prioritize:

- `africa` — AllAfrica, TechCabal, Daily Maverick, etc.
- `latin_america` — Folha, La Nación, Rest of World, etc.
- `middle_east` — Al Jazeera, Arab News, Middle East Eye, etc.
- `global_majority` — Al Jazeera, SCMP, Hindustan Times, AllAfrica, Global Voices, etc.
- `asia` — regional English-language outlets

Free tier is rate-limited (~100 requests/day); builds may skip NewsAPI when throttled.

### Supplement: DuckDuckGo News, RSS, outlets, Reddit

Via [`discover_viz_supplements()`](../src/discovery_hub.py):

- **DuckDuckGo News** — regional news search (codes aligned to focus themes; last ~90 days of a long range for supplements).
- **Google News RSS** — broad query.
- **Outlet feeds** — site-scoped searches (Reuters, AP, BBC, Bloomberg, NYT, WSJ, TechCrunch, ILO, etc.).
- **Reddit** — economics, jobs, AI, and labor-related subreddits.

Supplements use the shared labor/AI query in [`src/discover.py`](../src/discover.py).

## Regional focus

By default the dashboard biases discovery and display toward **global-majority regions**, especially:

- **Africa**
- **Latin America**
- **Middle East**

Configure with `VIZ_FOCUS_REGIONS` (see [`.env.example`](../.env.example)). Users can also check thematic regions on the dashboard form to steer pulls.

**Geographic balancing** (`VIZ_GEO_BALANCE=1`): when capping displayed rows (`IMPACT_VIZ_MAX_RECORDS`, default 400), the parser reserves a minimum per focus region (`VIZ_MIN_PER_FOCUS_REGION`, default 25) before filling remaining slots.

## Classification (parsed fields)

Each article is parsed in [`src/labor_impact_parse.py`](../src/labor_impact_parse.py) into:

| Field | How it is derived |
|-------|-------------------|
| **Date** | Article publication date |
| **Region** | Thematic label (Africa, Europe, Asia, …) from publisher country, discovery bucket, Event Registry metadata, or headline keywords |
| **Country** | Event Registry location concepts, publisher inference, or domain heuristics |
| **US state** | Inferred from headline/snippet text when country is United States |
| **Industry** | Concept tags + keyword rules (Technology, Entertainment, Retail & apparel, …) |
| **AI incident type** | Keyword rules: Job loss & layoffs, Automation & robotics, Platform & gig work, Policy & regulation, Creative rights & voice, etc. |
| **Job type** | Finer occupational bucket (garment workers, platform work, voice & creative, …) — used in aggregates, not always shown in the table |
| **Headline / URL / Source** | From the original article record |

Maps place incidents using **country centroids**; US state coordinates when a state is detected.

## Display limits

| Parameter | Default | Effect |
|-----------|---------|--------|
| `IMPACT_VIZ_MAX_RECORDS` | 400 | Max rows shown in Explore articles and embedded in static HTML |
| `VIZ_DISCOVER_MAX_RESULTS` | 150 | Cap per live Event Registry pull |
| `EVENTREGISTRY_VIZ_PER_YEAR` | 32 | Articles cached per calendar year |
| `VIZ_ER_PER_THEME` | 35 | Per-theme regional Event Registry pull |

Charts aggregate **all parsed records** in the selected window (subject to the cap above). Filter chips on the dashboard are **client-side** only.

## Production vs local

| | **morethancode.org** | **Local (`python -m src.web`)** |
|--|------------------------|----------------------------------|
| Hosting | GitHub Pages static HTML | Flask dev server |
| Data refresh | On each deploy (`WARM_VIZ_CACHE=1`, `VIZ_CACHE_REFRESH=1` in CI) | **Refresh data** button |
| News aggregator | Not published | Available at `/news` |
| API keys | GitHub Actions secrets | `.env` |

## Limitations

- **English-heavy**: queries and ranking favor English-language news; non-English stories appear when indexed with English metadata or outlets.
- **News bias**: sources are mainstream and digital news, not worker-organizer archives.
- **Rule-based tags**: industry and incident types are heuristic; misclassification is possible.
- **Not real-time on static site**: production data ages until the next deploy.
- **API quotas**: Event Registry free tier and NewsAPI limits can reduce counts on any given build.

Always follow the **linked original article** for full context. Summaries on the separate News aggregator (local only) may use LLM text and can err.

## Code references

- Discovery: [`src/impact_viz.py`](../src/impact_viz.py), [`src/eventregistry_client.py`](../src/eventregistry_client.py), [`src/discovery_hub.py`](../src/discovery_hub.py)
- Parsing: [`src/labor_impact_parse.py`](../src/labor_impact_parse.py)
- Static build: [`build_static.py`](../build_static.py), [`.github/workflows/pages.yml`](../.github/workflows/pages.yml)
- UI: [`templates/viz.html`](../templates/viz.html)

## Changelog

Document reflects the monitor as of June 2026. Configuration defaults live in [`.env.example`](../.env.example).

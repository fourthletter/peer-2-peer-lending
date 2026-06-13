# MoreThanCode AI & Labor Monitor

Part of [MoreThanCode.org](https://morethancode.org/). Tracks **AI's impact on the labor market** with two tools:

- **Labor Impact Dashboard** (`/incidents`) — map and charts of labor-impact events from Event Registry (Jan 2020–present)
- **News aggregator** (`/news`) — discover, rank, and preview a digest of relevant articles

Use the **web UI** to pick a date range and article count, or run the CLI with defaults (last 7 days, top 5).

## How it works

1. Discovers articles from **all available sources**:
   - **Broad Google News** — unrestricted search across publishers
   - **20+ major outlets** — Reuters, AP, BBC, Bloomberg, NYT, WSJ, HBR, ILO, etc.
   - **DuckDuckGo News** — 40+ global regions
   - **Reddit** — economics, jobs, AI, labor, and related subs
   - **NewsAPI.org** — all English publishers (optional API key)
   - **Event Registry / newsapi.ai** — 150k+ global sources in 60+ languages (optional API key)
2. **Fast rank** — scores candidates on snippets first, fetches full text only for winners
3. Ranks relevance with **Ollama** locally (keyword fallback when `RANK_LLM=0`)
4. Records sent URLs so they are not repeated (CLI email mode)

## Setup

### 1. Clone and install

```bash
cd news-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Start Ollama and pull a model (local dev)

```bash
# Install Ollama from https://ollama.com then:
ollama pull qwen2.5:3b
ollama serve   # usually runs automatically in the background
```

Set `RANK_LLM=1` in `.env` for LLM ranking locally. Use `RANK_LLM=0` on a server without Ollama.

### 3. Configure environment variables

Edit `.env` — see [`.env.example`](.env.example) for the full list. Key variables:

| Variable | Description |
|----------|-------------|
| `SITE_URL` | Public URL (`https://morethancode.org` in production) |
| `EVENTREGISTRY_API_KEY` | Required for Labor Impact Dashboard data |
| `NEWS_API_KEY` | Optional; auto-used in `hybrid` / `split` / `api` when set |
| `DISCOVERY_SOURCE` | `hybrid` (default): NewsAPI + Event Registry + DDGS/RSS/outlets together |
| `DISCOVERY_SUPPLEMENT` | `1` (default): in `split`/`api`, layer DDGS/RSS on API results |
| `RANK_LLM` | `0` = keyword ranking (production); `1` = Ollama ranking (local) |
| `SUMMARY_LLM` | `0` = snippet-only summaries (fastest) |
| `VIZ_LOAD_ON_STARTUP` | `0` = skip heavy viz load on boot (recommended in production) |
| `VIZ_CACHE_DIR` | Optional path for persistent viz cache (e.g. `/var/data/viz_cache`) |
| `FLASK_SECRET_KEY` | Session signing key (required in production) |
| `PORT` | Web server port (default `5050`) |

### 4. Web UI (recommended)

```bash
python -m src.web
```

Open [http://127.0.0.1:5050/incidents](http://127.0.0.1:5050/incidents) and [http://127.0.0.1:5050/news](http://127.0.0.1:5050/news).

### 5. Command line

```bash
python -m src.main --dry-run
python -m src.main --dry-run --from-date 2026-05-01 --to-date 2026-05-23 --count 10
python -m src.main --send --count 5
```

## Deploy to morethancode.org (GitHub Pages)

The public site is a **static export** of the Flask UI, built on every push to `main` by [`.github/workflows/pages.yml`](.github/workflows/pages.yml) and served from GitHub Pages.

### 1) GitHub repo setup

1. In **Settings → Secrets and variables → Actions**, add:
   - `EVENTREGISTRY_API_KEY` (optional but recommended — embeds dashboard data in the static build)
   - `NEWS_API_KEY` (optional)
   - `FLASK_SECRET_KEY` (any random string; unused on static pages but required by the app import)
2. In **Settings → Pages**, set **Source** to **GitHub Actions** (the workflow configures the rest).
3. Push to `main` or run **Actions → Deploy GitHub Pages → Run workflow**.

Local static build:

```bash
pip install -r requirements-build.txt
chmod +x scripts/build_static_site.sh
SITE_DOMAIN=morethancode.org ./scripts/build_static_site.sh
python -m http.server -d dist 8080
```

### 2) GoDaddy DNS (point away from Render)

Remove Render A records (`216.24.57.1`) and any domain forwarding. Add GitHub Pages records:

| Type | Name | Value |
|------|------|--------|
| **A** | `@` | `185.199.108.153` |
| **A** | `@` | `185.199.109.153` |
| **A** | `@` | `185.199.110.153` |
| **A** | `@` | `185.199.111.153` |
| **CNAME** | `www` | `fourthletter.github.io` |

Remove GitHub Pages parking A records from GoDaddy defaults and any **AAAA** records. In GitHub **Settings → Pages**, set custom domain to `morethancode.org` and enable **Enforce HTTPS** once the certificate is issued.

### 3) Verify

```bash
curl -sS https://morethancode.org/health.json
curl -sS -o /dev/null -w "incidents: %{http_code}\n" https://morethancode.org/incidents/
```

Expected: JSON on `/health.json`, **200** on `/incidents/`. Live search, digest preview, and **Refresh data** require running the app locally (`python -m src.web`).

### Local dev (full interactive app)

```bash
python -m src.web
```

Use `SITE_URL=http://127.0.0.1:5050` in `.env` so `/` stays on localhost.

## Project structure

```
src/
  main.py           CLI entry point
  web.py            Flask web UI
  pipeline.py       Shared digest pipeline
  impact_viz.py     Labor Impact Dashboard data
  viz_cache.py      Disk cache for viz payload
  discovery_hub.py  Merges discovery sources
  rank.py           Relevance scoring
templates/
  base.html         Shared layout (MoreThanCode branding)
  viz.html          Labor Impact Dashboard
  digest.html       News aggregator
static/
  site.css
.github/workflows/
  ci.yml            Import check on push/PR
  pages.yml         Build static site and deploy to GitHub Pages
build_static.py     Flask-Frozen export for Pages
scripts/
  build_static_site.sh  Build dist/ with CNAME for morethancode.org
```

## Notes

- Incident viz requires `EVENTREGISTRY_API_KEY`. Use **Refresh data** on `/incidents` after deploy.
- Production uses keyword ranking (`RANK_LLM=0`); local dev can enable Ollama with `RANK_LLM=1`.

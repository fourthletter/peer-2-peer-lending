# MoreThanCode AI & Labor Monitor

Part of [MoreThanCode.org](https://morethancode.org/). Tracks **AI's impact on the labor market** with two tools:

- **Incident visualization** (`/incidents`) — map and charts of labor-impact events from Event Registry (Jan 2020–present)
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

Set `RANK_LLM=1` in `.env` for LLM ranking locally. Production on Render uses `RANK_LLM=0`.

### 3. Configure environment variables

Edit `.env` — see [`.env.example`](.env.example) for the full list. Key variables:

| Variable | Description |
|----------|-------------|
| `SITE_URL` | Public URL (`https://morethancode.org` in production) |
| `EVENTREGISTRY_API_KEY` | Required for incident visualization |
| `NEWS_API_KEY` | Optional; used for Europe/North America in `split` discovery mode |
| `DISCOVERY_SOURCE` | `split` (default): NewsAPI for Europe/NA, Event Registry elsewhere |
| `RANK_LLM` | `0` = keyword ranking (Render); `1` = Ollama ranking (local) |
| `SUMMARY_LLM` | `0` = snippet-only summaries (fastest) |
| `VIZ_LOAD_ON_STARTUP` | `0` = skip heavy viz load on boot (recommended on Render) |
| `VIZ_CACHE_DIR` | Optional path for persistent viz cache (e.g. `/var/data/viz_cache` on Render) |
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

## Deploy to Render (morethancode.org)

This repo deploys from GitHub to [Render](https://render.com) (same pattern as the previous MoreThanCode site).

**Build:** `pip install -r requirements.txt`  
**Start:** `gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 src.web:app`

### 1) Create or update Render web service

Connect this GitHub repo (`fourthletter/peer-2-peer-lending` until renamed). Confirm:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 src.web:app`
- Auto-Deploy enabled

Or apply the blueprint in [`render.yaml`](render.yaml).

### 2) Set Render environment variables

| Variable | Value |
|----------|-------|
| `SITE_URL` | `https://morethancode.org` |
| `FLASK_SECRET_KEY` | strong random string |
| `EVENTREGISTRY_API_KEY` | your Event Registry key |
| `NEWS_API_KEY` | optional |
| `DISCOVERY_SOURCE` | `split` |
| `VIZ_LOAD_ON_STARTUP` | `0` |
| `RANK_LLM` | `0` |
| `SUMMARY_LLM` | `0` |
| `VIZ_CACHE_DIR` | `/var/data/viz_cache` (with persistent disk mounted at `/var/data`) |

Add a **1 GB persistent disk** mounted at `/var/data` so incident cache survives redeploys.

### 3) Connect GitHub Actions to Render

Add repository secret `RENDER_DEPLOY_HOOK_URL` with your Render deploy hook URL. Pushes to `main` trigger [`.github/workflows/deploy-render.yml`](.github/workflows/deploy-render.yml).

### 4) Custom domain and DNS

1. Add custom domain `morethancode.org` on the Render service.
2. In your DNS provider, point `morethancode.org` to Render (A/CNAME per Render's instructions).
3. **Disable GitHub Pages** on this repo — Render owns the domain; do not publish a `CNAME` via Pages.

### 5) Verify production

- `GET /health` → `{"ok": true, "runtime": "flask"}`
- `/` redirects to `/incidents`
- `/news` preview works with keyword ranking

## Project structure

```
src/
  main.py           CLI entry point
  web.py            Flask web UI
  pipeline.py       Shared digest pipeline
  impact_viz.py     Incident visualization data
  viz_cache.py      Disk cache for viz payload
  discovery_hub.py  Merges discovery sources
  rank.py           Relevance scoring
templates/
  base.html         Shared layout (MoreThanCode branding)
  viz.html          Incident visualization
  digest.html       News aggregator
static/
  site.css
.github/workflows/
  ci.yml            Import check on push/PR
  deploy-render.yml Trigger Render on push to main
render.yaml         Render blueprint
```

## Notes

- The GitHub repo may still be named `peer-2-peer-lending`; rename it in GitHub Settings if desired.
- Incident viz requires `EVENTREGISTRY_API_KEY`. Use **Refresh data** on `/incidents` after deploy.
- Production uses keyword ranking (`RANK_LLM=0`); local dev can enable Ollama with `RANK_LLM=1`.

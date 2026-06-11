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

Set `RANK_LLM=1` in `.env` for LLM ranking locally. Use `RANK_LLM=0` on a server without Ollama.

### 3. Configure environment variables

Edit `.env` — see [`.env.example`](.env.example) for the full list. Key variables:

| Variable | Description |
|----------|-------------|
| `SITE_URL` | Public URL (`https://morethancode.org` in production) |
| `EVENTREGISTRY_API_KEY` | Required for incident visualization |
| `NEWS_API_KEY` | Optional; used for Europe/North America in `split` discovery mode |
| `DISCOVERY_SOURCE` | `split` (default): NewsAPI for Europe/NA, Event Registry elsewhere |
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

## Production (optional)

Run the app on any Linux host with Python 3.12+, your `.env` secrets, and a reverse proxy for HTTPS.

```bash
pip install -r requirements.txt
export $(grep -v '^#' .env | xargs)   # or use systemd EnvironmentFile
gunicorn --bind 0.0.0.0:5050 --workers 2 --timeout 120 src.web:app
```

Set `SITE_URL=https://morethancode.org`, `FLASK_SECRET_KEY`, `EVENTREGISTRY_API_KEY`, `RANK_LLM=0`, and `SUMMARY_LLM=0` in the server environment. Put Caddy or nginx in front for TLS, then point GoDaddy DNS at that server’s IP.

Health check: `GET /health` → `{"ok": true, "runtime": "flask"}`.

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
```

## Notes

- Incident viz requires `EVENTREGISTRY_API_KEY`. Use **Refresh data** on `/incidents` after deploy.
- Production uses keyword ranking (`RANK_LLM=0`); local dev can enable Ollama with `RANK_LLM=1`.

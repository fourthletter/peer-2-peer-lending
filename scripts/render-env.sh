#!/usr/bin/env bash
# Set production secrets on Render via CLI (no dashboard).
# Requires: brew install render (or npm i -g @render/cli) && render login
set -euo pipefail

SERVICE="${RENDER_SERVICE:-ai-labor-monitor}"

if ! command -v render >/dev/null 2>&1; then
  echo "Install Render CLI: https://render.com/docs/cli" >&2
  exit 1
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

for key in EVENTREGISTRY_API_KEY NEWS_API_KEY; do
  val="${!key:-}"
  if [[ -n "$val" ]]; then
    echo "Setting $key on $SERVICE..."
    render env set "$key=$val" --service "$SERVICE"
  fi
done

echo "Done. Push to main to deploy (autoDeployTrigger: commit)."

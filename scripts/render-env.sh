#!/usr/bin/env bash
# Push secrets from .env to Render (ai-labor-monitor).
set -euo pipefail

SERVICE_ID="${RENDER_SERVICE_ID:-srv-d8lg5hf7f7vs73f7gmlg}"
RENDER_CONFIG="${RENDER_CONFIG:-$HOME/.render/cli.yaml}"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

API_KEY=""
if [[ -f "$RENDER_CONFIG" ]]; then
  API_KEY=$(grep '^    key:' "$RENDER_CONFIG" | awk '{print $2}')
fi
if [[ -z "$API_KEY" && -n "${RENDER_API_KEY:-}" ]]; then
  API_KEY="$RENDER_API_KEY"
fi
if [[ -z "$API_KEY" ]]; then
  echo "No Render API key. Run: render login" >&2
  exit 1
fi

for key in EVENTREGISTRY_API_KEY NEWS_API_KEY FLASK_SECRET_KEY; do
  val="${!key:-}"
  if [[ -n "$val" ]]; then
    echo "Setting $key on $SERVICE_ID..."
    http=$(curl -sS -o /tmp/render-env-out.json -w "%{http_code}" -X PUT \
      "https://api.render.com/v1/services/${SERVICE_ID}/env-vars/${key}" \
      -H "Authorization: Bearer ${API_KEY}" \
      -H "Content-Type: application/json" \
      -d "{\"value\":\"${val}\"}")
    if [[ "$http" != "200" && "$http" != "201" ]]; then
      echo "Failed ($http): $key" >&2
      cat /tmp/render-env-out.json >&2
      exit 1
    fi
  else
    echo "Skipping $key (not set in .env)"
  fi
done

echo "Done."

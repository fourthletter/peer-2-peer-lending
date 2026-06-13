#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export STATIC_BUILD="${STATIC_BUILD:-1}"
export SITE_URL="${SITE_URL:-https://morethancode.org}"
export VIZ_LOAD_ON_STARTUP="${VIZ_LOAD_ON_STARTUP:-0}"

python build_static.py
touch dist/.nojekyll

if [ -n "${SITE_DOMAIN:-}" ]; then
  echo "$SITE_DOMAIN" > dist/CNAME
elif [ "${WRITE_CNAME:-1}" = "1" ]; then
  echo "morethancode.org" > dist/CNAME
fi

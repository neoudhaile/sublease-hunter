#!/usr/bin/env bash
# Full pipeline: scrape -> extract -> filter/rank -> notion sync.
# Pass --fixtures to test, --days N for light scrapes, --group X for one group.
set -euo pipefail
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"

# Load secrets (NOTION_TOKEN, APIFY_TOKEN) if present
set -a
[ -f .env ] && source .env
set +a

.venv/bin/python -m pipeline.scrape "$@"
.venv/bin/python -m pipeline.extract
.venv/bin/python -m pipeline.enrich
.venv/bin/python -m pipeline.gender
.venv/bin/python -m pipeline.filter_rank
.venv/bin/python -m pipeline.notion_push

echo
echo "== Results =="
echo "All candidates:  out/candidates.csv"
echo "New this run:    out/new_candidates.csv"
echo "Coverage report: out/coverage_report.md"

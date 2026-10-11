#!/usr/bin/env bash
# Wipe all scraped data, extraction cache, and outputs for a fresh start.
# Does NOT touch your forage/monitor login sessions.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf cache out raw
mkdir -p cache out raw
echo "Reset complete: cache/, out/, raw/ cleared."

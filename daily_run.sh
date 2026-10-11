#!/usr/bin/env bash
# Scheduled run (launchd / cron, once a day). Sweeps every readable group in the
# registry, extracts, ranks, pushes new candidates to Notion, and notifies ONLY
# when a genuinely good lead appears (tier A or B).
#
# Once a day is deliberate. An earlier every-2h schedule with a rotating 5-group
# slice turned up plenty of rows and nothing above tier C: the extra passes were
# re-reading the same feeds. Facebook feeds do not move fast enough to be worth
# more than one sweep a day.
#
# Posting and DMs are deliberately NOT here: both need the logged-in browser
# session and both have Facebook rate limits worth respecting by hand.
#
# Install the schedule (macOS):
#   cp com.example.sublease-hunter.plist ~/Library/LaunchAgents/   # edit paths first
#   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.sublease-hunter.plist
# Stop it:
#   launchctl bootout gui/$(id -u)/com.example.sublease-hunter
set -euo pipefail
cd "$(dirname "$0")"

GROUPS_PER_RUN=25           # above the group count, so one run sweeps them all

# Stop running once the window has started: a sublet that begins tomorrow is not
# filled by a lead found tomorrow. Read from config so there is one source of truth.
STOP_AFTER="$(python3 -c '
import sys, yaml, pathlib
for name in ("config.yaml", "groups.yaml"):
    p = pathlib.Path(name)
    if p.exists():
        print(yaml.safe_load(p.read_text())["window"]["start"]); sys.exit()
sys.exit("no config.yaml")
')"

if [[ "$(date +%Y-%m-%d)" > "$STOP_AFTER" ]]; then
  echo "$(date): past the window start ($STOP_AFTER) — skipping."
  exit 0
fi

mkdir -p logs
echo "=== $(date) ==="

# run.sh sources .env for its own steps, but the pipeline modules called
# directly below need NOTION_TOKEN too (missing it silently skipped the
# backfill on the first test run).
set -a
[ -f .env ] && source .env
set +a
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"

notify() {  # notify <title> <message>
  osascript -e "display notification \"$2\" with title \"$1\"" 2>/dev/null || true
}

if ! ./run.sh --days 3 --limit 80 --rotate "$GROUPS_PER_RUN"; then
  notify "sublease-hunter" "Run FAILED — check logs/daily.log (FB session expired?)"
  exit 1
fi

# Push labels and current tiers onto cards already on the board (notion_push
# only ever ADDS cards, so later columns stay blank without this).
# Do NOT re-run filter_rank here: it would rewrite new_candidates.csv empty and
# silence the notification below. The gender pass now lives inside run.sh.
.venv/bin/python -m pipeline.notion_backfill || echo "notion backfill failed, continuing"

# Only shout about leads actually worth acting on. Reads new_candidates.csv for
# "what appeared this run"; out/to_contact.csv is the list to actually message
# from, since it already excludes anyone in the contact ledger.
python3 - <<'PY'
import csv, json, os, subprocess
from pathlib import Path
new = Path("out/new_candidates.csv")
if not new.exists():
    raise SystemExit
rows = [r for r in csv.DictReader(new.open()) if r["tier"] in ("A", "B")]
if not rows:
    print("no new tier A/B leads this run")
    raise SystemExit
rows.sort(key=lambda r: (r["tier"], -int(r["days_covered"] or 0)))
best = rows[0]
msg = (f'{len(rows)} new tier A/B: {best["name"]} '
       f'({best["tier"]}, {best["days_covered"]}d, '
       f'{best["wants_start"] or "open"} to {best["wants_end"] or "open"})')
print(msg)
subprocess.run(["osascript", "-e",
                f'display notification "{msg}" with title "sublease-hunter: new lead"'],
               check=False)
Path("out/pending_review.json").write_text(json.dumps(
    [{k: r[k] for k in ("tier","name","wants_start","wants_end","days_covered",
                        "budget","group","post_url","profile_url","draft_message")}
     for r in rows], indent=1))
PY

echo "=== done $(date) ==="

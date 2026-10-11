"""Update EXISTING Notion candidate cards from candidates.csv.

notion_push.py is add-only by design, so a column added later stays blank on
every card already on the board. That is what happened to Gender: the column
existed, nothing ever filled it in. This script closes that gap.

It only writes the properties listed in BACKFILL_FIELDS, and it never touches
Status, Tier Reason or anything a human edits by hand. Cards are matched on the
Key property, which holds the post URL.

Usage:
  python -m pipeline.notion_backfill            # fill only blank fields
  python -m pipeline.notion_backfill --overwrite  # also replace existing values
  python -m pipeline.notion_backfill --dry-run
"""
import csv
import os
import sys
import time
import urllib.error

from . import notion_push
from .common import CACHE_DIR, OUT_DIR, load_config, log, read_jsonl
from .notion_push import api, load_state, rich, sel

# Filled only when the card's field is blank (or with --overwrite).
BACKFILL_FIELDS = {
    "Person": ("person_key", lambda v: {"rich_text": rich(v)}),
    "Gender": ("likely_gender", lambda v: sel(v)),
    "Gender Source": ("gender_basis", lambda v: sel(v)),
    "Term": ("term", lambda v: sel(v)),
}

# Always rewritten to match the current ranking. Tier is recomputed every run
# (stale posts drop out, early starters get demoted), but a card keeps whatever
# Tier it was born with, so the board showed ~100 Tier A when 8 were real.
# Status is deliberately absent: that column belongs to the human.
ALWAYS_SYNC = {
    "Person": ("person_key", lambda v: {"rich_text": rich(v)}),
    "Tier": ("tier", lambda v: sel(v)),
    "Tier Reason": ("tier_reason", lambda v: {"rich_text": rich(v)}),
    "Days": ("days_covered", lambda v: {"number": int(v)}),
    "Fit": ("fit", lambda v: sel(v)),
}


def is_blank(prop):
    if not prop:
        return True
    t = prop.get("type")
    if t == "select":
        return prop.get("select") is None
    if t == "rich_text":
        return not prop.get("rich_text")
    if t == "number":
        return prop.get("number") is None
    if t == "date":
        return prop.get("date") is None
    return False


def main() -> None:
    overwrite = "--overwrite" in sys.argv
    dry = "--dry-run" in sys.argv

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        log("NOTION_TOKEN not set")
        sys.exit(1)

    cfg = load_config()
    notion_push.configure(cfg)
    state = load_state()
    db_id = state.get("database_id")
    if not db_id:
        log("no candidates database in state; run notion_push first")
        sys.exit(1)

    notion_push.migrate_schema(token, db_id)

    name_gender = {r["name"]: r for r in read_jsonl(CACHE_DIR / "gender.jsonl")}
    by_key = {}
    with open(OUT_DIR / "candidates.csv") as f:
        for row in csv.DictReader(f):
            by_key[notion_push.sync_key(row)] = row

    pages, cursor = [], None
    while True:
        body = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
        page = api(token, "POST", f"/databases/{db_id}/query", body)
        pages += page["results"]
        if not page.get("has_more"):
            break
        cursor = page["next_cursor"]
    log(f"{len(pages)} cards on the board, {len(by_key)} rows in candidates.csv")

    updated = unmatched = skipped = 0
    for pg in pages:
        props = pg["properties"]
        key = "".join(t["plain_text"] for t in props.get("Key", {}).get("rich_text", []))
        row = by_key.get(key)
        extra_active = None  # Active column removed; Status carries the state
        if not row:
            # Cards whose post has aged out of candidates.csv still deserve a
            # label, so fall back to the name cache using the card's own title.
            unmatched += 1
            title = "".join(t["plain_text"] for t in props.get("Name", {}).get("title", []))
            parts = title.strip().split()
            guess = name_gender.get(parts[0].lower()) if parts else None
            if not guess:
                if extra_active is not None:
                    try:
                        api(token, "PATCH", f"/pages/{pg['id']}",
                            {"properties": {"Active": extra_active}})
                        time.sleep(0.35)
                    except urllib.error.HTTPError:
                        pass
                continue
            conf = guess.get("confidence", "?")
            basis = f"name ({conf})" if guess["gender"] in ("male", "female") else "name"
            row = {"likely_gender": guess["gender"], "gender_basis": basis}
        patch = {}
        for prop_name, (col, build) in BACKFILL_FIELDS.items():
            value = (row.get(col) or "").strip()
            if not value:
                continue
            if overwrite or is_blank(props.get(prop_name)):
                patch[prop_name] = build(value)
        if key in by_key:  # only rows with a live ranking behind them
            for prop_name, (col, build) in ALWAYS_SYNC.items():
                value = str(row.get(col) or "").strip()
                if value:
                    patch[prop_name] = build(value)
        if extra_active is not None:
            patch["Active"] = extra_active
        if not patch:
            skipped += 1
            continue
        if dry:
            name = "".join(t["plain_text"] for t in props["Name"]["title"])
            log(f"  would set {list(patch)} on {name}")
            updated += 1
            continue
        try:
            api(token, "PATCH", f"/pages/{pg['id']}", {"properties": patch})
            updated += 1
        except urllib.error.HTTPError as e:
            log(f"  ERROR {e.code}: {e.read().decode()[:160]}")
        time.sleep(0.35)  # Notion allows roughly 3 requests a second

    log(f"backfill {'(dry run) ' if dry else ''}done: {updated} updated, "
        f"{skipped} already complete, {unmatched} labelled from the name cache "
        f"(no current candidates.csv row)")


if __name__ == "__main__":
    main()

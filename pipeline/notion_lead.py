"""Add an INBOUND lead to the candidates board.

The scraper only ever finds people who posted in a group. Someone who messages
you first after seeing the listing never appears in candidates.csv, so the
warmest contacts were the ones tracked nowhere. This puts them on the same
board with the same columns.

Usage:
  python -m pipeline.notion_lead "Full Name" --wants 2027-03-01:2027-04-15 \
      [--status "DM'd"] [--note "what they said"] [--budget "$3000"] \
      [--thread https://facebook.com/messages/t/123] [--tier A]

Dates are YYYY-MM-DD:YYYY-MM-DD; use "open" for either side.
Keyed as inbound:<name> so re-running updates rather than duplicates.
"""
import argparse
import os
import sys
import urllib.error
from datetime import date

from . import notion_push
from .common import CACHE_DIR, load_config, log, read_jsonl
from .notion_push import api, load_state, rich, sel


def parse_span(text):
    if not text:
        return None, None
    a, _, b = text.partition(":")
    clean = lambda v: None if v in ("", "open") else v
    return clean(a), clean(b)


def days_covered(start, end, w_start, w_end):
    s = max(start or w_start.isoformat(), w_start.isoformat())
    e = min(end or w_end.isoformat(), w_end.isoformat())
    if e < s:
        return 0
    return (date.fromisoformat(e) - date.fromisoformat(s)).days + 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--wants", default="")
    ap.add_argument("--status", default="New")
    ap.add_argument("--note", default="")
    ap.add_argument("--budget", default="")
    ap.add_argument("--thread", default="")
    ap.add_argument("--tier", default="")
    args = ap.parse_args()

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

    w_start, w_end = cfg["window"]["start"], cfg["window"]["end"]
    start, end = parse_span(args.wants)
    days = days_covered(start, end, w_start, w_end)
    tier = args.tier or ("A" if days >= (w_end - w_start).days * 0.9 else "B")

    first = args.name.strip().split()[0].lower()
    guess = {r["name"]: r for r in read_jsonl(CACHE_DIR / "gender.jsonl")}.get(first)
    gender = guess["gender"] if guess else "unknown"
    basis = f"name ({guess.get('confidence', '?')})" if guess else ""

    key = f"inbound:{args.name.strip().lower()}"
    props = {
        "Name": {"title": rich(args.name)},
        "Status": sel(args.status),
        "Tier": sel(tier),
        "Tier Reason": {"rich_text": rich(
            f"inbound lead, covers {days}/{(w_end - w_start).days + 1} days")},
        "Days": {"number": days},
        "Fit": sel("inbound"),
        "Group": sel("Inbound (messaged us)"),
        "Gender": sel(gender),
        "Gender Source": sel(basis),
        "Budget": {"rich_text": rich(args.budget)},
        "Active": {"checkbox": True},
        "Post": {"url": args.thread or None},
        "Key": {"rich_text": rich(key)},
    }
    if start:
        props["Wants Start"] = {"date": {"start": start}}
    if end:
        props["Wants End"] = {"date": {"start": end}}

    existing = api(token, "POST", f"/databases/{db_id}/query",
                   {"filter": {"property": "Key", "rich_text": {"equals": key}}}
                   ).get("results", [])
    children = [{"object": "block", "type": "paragraph",
                 "paragraph": {"rich_text": rich(args.note)}}] if args.note else []
    try:
        if existing:
            api(token, "PATCH", f"/pages/{existing[0]['id']}", {"properties": props})
            log(f"updated inbound lead: {args.name} ({tier}, {days}d, {gender})")
        else:
            api(token, "POST", "/pages", {"parent": {"database_id": db_id},
                                          "properties": props, "children": children})
            log(f"added inbound lead: {args.name} ({tier}, {days}d, {gender})")
    except urllib.error.HTTPError as e:
        log(f"Notion ERROR {e.code}: {e.read().decode()[:200]}")
        sys.exit(1)


if __name__ == "__main__":
    main()

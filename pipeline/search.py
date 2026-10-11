"""The three passes behind "search". Read-only: it decides, it never sends.

Each pass answers one question off the Notion boards and the group registry,
then prints a worklist. Acting on a worklist (sending the DM, making the post)
is done by the agent through the browser, and the result is written back to
Notion with `pipeline.notion_status` or `pipeline.notion_posts`.

  conversations  who we messaged a day or more ago and never heard from
  posts          groups we can post in but have not posted in this period
  outreach       good-fit people nobody has contacted yet

Usage:
  python -m pipeline.search conversations [--quiet-days N] [--limit N]
  python -m pipeline.search posts [--limit N]
  python -m pipeline.search outreach [--limit N]
  python -m pipeline.search all
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime

import yaml

from . import notion_push
from .common import OUT_DIR, load_config, log
from .notion_push import api, load_state

# Facebook's cap on message requests to strangers. Replies inside an existing
# thread do not count against it, but first contacts do.
DM_CAP_PER_DAY = 10

# Statuses that mean we are waiting on them, so a nudge is fair game.
AWAITING_REPLY = {"DM'd", "Commented"}
# Statuses that mean leave them alone.
CLOSED = {"Ruled Out"}


def _pages(token, db_id):
    out, cursor = [], None
    while True:
        body = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
        page = api(token, "POST", f"/databases/{db_id}/query", body)
        out += page["results"]
        if not page.get("has_more"):
            break
        cursor = page["next_cursor"]
    return out


def _txt(props, key):
    return "".join(t["plain_text"] for t in props.get(key, {}).get("rich_text", []))


def _title(props, key="Name"):
    """The People board's title column is "Name"; the Posts board's is "Group".
    Reading the wrong one silently returns "" and every group looks unposted."""
    return "".join(t["plain_text"] for t in props.get(key, {}).get("title", [])).strip()


def _sel(props, key):
    return (props.get(key, {}).get("select") or {}).get("name") or ""


def _date(props, key):
    d = props.get(key, {}).get("date")
    return (d or {}).get("start") or ""


def _num(props, key):
    return props.get(key, {}).get("number") or 0


def _connect():
    cfg = load_config()
    notion_push.configure(cfg)
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        log("NOTION_TOKEN not set — Notion is the datastore, so nothing to read")
        sys.exit(1)
    return cfg, token, load_state()


# --------------------------------------------------------------------------
def conversations(quiet_days=1, limit=None):
    """People we contacted at least `quiet_days` ago who never wrote back.

    Replied cards come first and are NOT nudges: those are live conversations
    that need a human answer, so they are listed separately and loudly.
    """
    _, token, state = _connect()
    pages = _pages(token, state["database_id"])
    today = date.today()

    live, quiet = [], []
    for p in pages:
        pr = p["properties"]
        status = _sel(pr, "Status")
        if status in CLOSED or not status or status == "New":
            continue
        when = _date(pr, "Contacted")
        age = (today - date.fromisoformat(when)).days if when else None
        row = {
            "name": _title(pr), "status": status, "contacted": when, "age_days": age,
            "tier": _sel(pr, "Tier"), "days": int(_num(pr, "Days")),
            "gender": _sel(pr, "Gender"), "post": pr.get("Post", {}).get("url") or "",
            "profile": pr.get("Profile", {}).get("url") or "",
            "person": _txt(pr, "Person"), "key": _txt(pr, "Key"),
        }
        if status == "Replied":
            live.append(row)
        elif status in AWAITING_REPLY and age is not None and age >= quiet_days:
            quiet.append(row)

    # A person with two surviving cards must not appear twice in a worklist.
    def dedupe(rows):
        seen, out = set(), []
        for r in sorted(rows, key=lambda r: (r["tier"] or "Z", -r["days"])):
            # Key on the display name, not Person: a straggler card can have
            # an empty Person and would otherwise slip through as a second row.
            k = r["name"].strip().lower() or r["person"]
            if k in seen:
                continue
            seen.add(k)
            out.append(r)
        return out

    live, quiet = dedupe(live), dedupe(quiet)
    live.sort(key=lambda r: -r["days"])
    # Best fit first: a nudge budget is scarce, spend it on the best rooms-fit.
    quiet.sort(key=lambda r: (r["tier"] or "Z", -r["days"], r["contacted"]))
    if limit:
        quiet = quiet[:limit]
    return {"live": live, "quiet": quiet}


# --------------------------------------------------------------------------
def posts(limit=None):
    """Groups we are a member of and can post in, with no post this period."""
    cfg, token, state = _connect()
    reg = yaml.safe_load(open(os.path.expanduser(cfg["groups_registry"])))

    posted = {}
    for p in _pages(token, state["posts_database_id"]):
        pr = p["properties"]
        posted[_title(pr, "Group")] = {"status": _sel(pr, "Status"),
                              "url": pr.get("Post URL", {}).get("url") or "",
                              "notes": _txt(pr, "Notes")}

    todo, blocked = [], []
    for g in reg["groups"]:
        if g.get("status", "active") != "active":
            continue
        rec = posted.get(g["name"], {})
        st = rec.get("status", "")
        if st in ("Live", "Pending approval"):
            continue  # already carrying this period's listing
        entry = {"name": g["name"], "id": g.get("id"), "members": g.get("members") or 0,
                 "post": g.get("post"), "requires_price": g.get("requires_price"),
                 "board_status": st or "(not on board)", "notes": g.get("notes", "")}
        if g.get("post") in ("ok", "admin-queue", "untested"):
            todo.append(entry)
        else:
            blocked.append(entry)

    todo.sort(key=lambda e: -(e["members"] or 0))
    if limit:
        todo = todo[:limit]
    return {"todo": todo, "blocked": blocked}


# --------------------------------------------------------------------------
def outreach(limit=None):
    """Good-fit people nobody has contacted yet.

    If config sets preferences.prefer_gender, names that read confidently as the
    other gender are held back for you to decide on by hand rather than being
    messaged. "unisex"/"unknown" stay in the send list on purpose: a name-based
    guess is wrong often enough that dropping them would lose real candidates,
    and you can eyeball a profile in seconds. Held-back people are never
    deleted — they keep their card, and you can set them Ruled Out yourself.
    """
    prefer = load_config().get("preferences", {}).get("prefer_gender", "none")
    rows = []
    path = OUT_DIR / "to_contact.csv"
    if not path.exists():
        log("out/to_contact.csv missing — run pipeline.filter_rank first")
        return {"send": [], "held": [], "prefer": prefer}
    import csv
    with open(path) as f:
        rows = list(csv.DictReader(f))

    # With prefer_gender "none" (the default) nothing is held back.
    other = {"male": "female", "female": "male"}.get(prefer)
    send = [r for r in rows if not other or r.get("likely_gender") != other]
    held = [r for r in rows if other and r.get("likely_gender") == other]
    send.sort(key=lambda r: (r["tier"], -int(r["days_covered"] or 0)))
    if limit:
        send = send[:limit]
    return {"send": send, "held": held, "prefer": prefer}


# --------------------------------------------------------------------------
def _print_conversations(res):
    print(f"\n=== CONVERSATIONS ===")
    if res["live"]:
        print(f"\nLIVE — they replied, need an answer ({len(res['live'])}):")
        for r in res["live"]:
            print(f"  {r['tier']} {r['days']:>2}d  {r['name'][:26]:26} replied; contacted {r['contacted']}")
    else:
        print("\nLIVE: none")
    print(f"\nGONE QUIET — nudge candidates ({len(res['quiet'])}):")
    for r in res["quiet"]:
        print(f"  {r['tier']} {r['days']:>2}d  {r['name'][:26]:26} {r['status']:10} "
              f"{r['age_days']}d ago  {r['gender'] or '-'}")
    if not res["quiet"]:
        print("  none")


def _print_posts(res):
    print(f"\n=== POSTS ===")
    print(f"\nCAN POST, no listing this period ({len(res['todo'])}):")
    for e in res["todo"]:
        price = " [REQUIRES PRICE]" if e["requires_price"] is True else ""
        print(f"  {e['members'] or 0:>7,} members  {e['name'][:46]:46} "
              f"{e['post']:12} {e['board_status']}{price}")
    if not res["todo"]:
        print("  none")
    if res["blocked"]:
        print(f"\nBlocked / not joined ({len(res['blocked'])}):")
        for e in res["blocked"]:
            print(f"  {e['name'][:46]:46} {e['post']}")


def _print_outreach(res):
    print(f"\n=== OUTREACH ===")
    print(f"\nTO CONTACT ({len(res['send'])}):")
    for r in res["send"]:
        print(f"  {r['tier']} {r['days_covered']:>2}d  {r['name'][:26]:26} "
              f"{r['wants_start'] or 'open'}->{r['wants_end'] or 'open'}  "
              f"{r['likely_gender']:7} {(r['budget'] or '-')[:16]}")
    if not res["send"]:
        print("  none")
    if res.get("held"):
        other = {"male": "female", "female": "male"}[res["prefer"]]
        print(f"\nHeld back, name reads {other} ({len(res['held'])}):")
        for r in res["held"]:
            print(f"  {r['tier']} {r['days_covered']:>2}d  {r['name'][:26]:26}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pass_name", choices=["conversations", "posts", "outreach", "all"])
    ap.add_argument("--quiet-days", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    out = {}
    if a.pass_name in ("conversations", "all"):
        out["conversations"] = conversations(a.quiet_days, a.limit)
    if a.pass_name in ("posts", "all"):
        out["posts"] = posts(a.limit)
    if a.pass_name in ("outreach", "all"):
        out["outreach"] = outreach(a.limit)

    if a.json:
        print(json.dumps(out, indent=1, default=str))
        return
    if "conversations" in out:
        _print_conversations(out["conversations"])
    if "posts" in out:
        _print_posts(out["posts"])
    if "outreach" in out:
        _print_outreach(out["outreach"])
    print(f"\nDM cap is {DM_CAP_PER_DAY} new message requests per 24h; "
          "replies in existing threads don't count.")


if __name__ == "__main__":
    main()

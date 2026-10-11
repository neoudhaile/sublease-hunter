"""Track the user's own listing posts across groups in a Notion "My Posts" db.

Usage: python -m pipeline.notion_posts add "<group>" "<post-url-or-empty>" "<status>" "<notes>"
       python -m pipeline.notion_posts seed
Status: Live | Pending approval | Planned | Blocked
`add` upserts by group name so re-runs update rather than duplicate.
`seed` adds a row for every postable group in the shared registry
(groups/<city>.yaml) that the board doesn't have yet; it never touches existing
rows, so statuses you've set are safe.
"""
import os
import sys

from .common import log
from . import notion_push
from .notion_push import api, load_state, save_state, rich

POSTS_DB_PROPERTIES = {
    "Group": {"title": {}},
    "Status": {"select": {"options": [
        {"name": "Live", "color": "green"},
        {"name": "Pending approval", "color": "yellow"},
        {"name": "Planned", "color": "blue"},
        {"name": "Blocked", "color": "red"},
    ]}},
    "Post URL": {"url": {}},
    "Posted On": {"date": {}},
    "Responses": {"number": {}},
    "Members": {"number": {}},
    "Group Link": {"url": {}},
    "Notes": {"rich_text": {}},
}


def ensure_posts_db(token, parent, state, title="My Posts"):
    if state.get("posts_database_id"):
        return state["posts_database_id"]
    result = api(token, "POST", "/databases", {
        "parent": {"type": "page_id", "page_id": parent},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": POSTS_DB_PROPERTIES,
    })
    state["posts_database_id"] = result["id"]
    save_state(state)
    log(f"Created Notion database '{title}' ({result['id']})")
    return result["id"]


def upsert(token, db_id, group, url, status, notes, extra=None):
    existing = api(token, "POST", f"/databases/{db_id}/query", {
        "filter": {"property": "Group", "title": {"equals": group}},
    }).get("results", [])
    props = {
        "Group": {"title": rich(group)},
        "Status": {"select": {"name": status}},
        "Post URL": {"url": url or None},
        "Notes": {"rich_text": rich(notes)},
        **(extra or {}),
    }
    if status == "Live" and url and not (extra or {}).get("Posted On"):
        from datetime import date
        props["Posted On"] = {"date": {"start": date.today().isoformat()}}
    if existing:
        api(token, "PATCH", f"/pages/{existing[0]['id']}", {"properties": props})
        log(f"updated: {group} -> {status}")
    else:
        api(token, "POST", "/pages", {
            "parent": {"database_id": db_id}, "properties": props,
        })
        log(f"added: {group} -> {status}")


SEED_STATUS = {"ok": "Planned", "admin-queue": "Planned", "untested": "Planned",
               "blocked": "Blocked", "not-joined": "Planned"}


def seed(token, db_id, registry_path, cfg=None):
    import yaml
    from pathlib import Path
    reg = yaml.safe_load(Path(registry_path).expanduser().read_text())
    existing = set()
    cursor = None
    while True:
        body = {"start_cursor": cursor} if cursor else {}
        page = api(token, "POST", f"/databases/{db_id}/query", body)
        for r in page.get("results", []):
            t = r["properties"]["Group"]["title"]
            existing.add("".join(x["plain_text"] for x in t))
        if not page.get("has_more"):
            break
        cursor = page["next_cursor"]
    added = 0
    for g in reg.get("groups", []):
        if g.get("status", "active") != "active" or g["name"] in existing:
            continue
        post = g.get("post")
        if post not in SEED_STATUS:
            continue
        bits = {"admin-queue": "posts go to admin queue",
                "not-joined": "join first", "untested": "never posted here"}.get(post)
        notes = "; ".join(x for x in [bits, g.get("notes")] if x)
        if g.get("requires_price") is True:
            # Some groups reject a listing with no number in it. The rate lives
            # in config so the reminder can't drift from what you actually quote.
            rate = (cfg or {}).get("listing", {}).get("nightly_rate")
            line = f"add 'Price: ${rate} a night'" if rate else "a price line is required"
            notes = f"REQUIRES PRICE: {line}; " + notes
        props = {
            "Group": {"title": rich(g["name"])},
            "Status": {"select": {"name": SEED_STATUS[post]}},
            "Notes": {"rich_text": rich(notes)},
        }
        if g.get("members"):
            props["Members"] = {"number": g["members"]}
        if g.get("id"):
            props["Group Link"] = {"url": f"https://www.facebook.com/groups/{g['id']}"}
        api(token, "POST", "/pages", {"parent": {"database_id": db_id}, "properties": props})
        added += 1
    log(f"seed: {added} group(s) added, {len(existing)} already on the board")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("add", "seed") or (
            sys.argv[1] == "add" and len(sys.argv) < 5):
        print(__doc__)
        sys.exit(1)

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        log("NOTION_TOKEN not set")
        sys.exit(1)
    from .common import load_config
    cfg = load_config()
    notion_cfg = notion_push.configure(cfg)
    parent = str(notion_cfg.get("posts_page_id")
                 or notion_cfg.get("parent_page_id", "")).replace("-", "")
    state = load_state()
    db_id = ensure_posts_db(token, parent, state, notion_cfg.get("posts_db_title", "My Posts"))
    if sys.argv[1] == "seed":
        seed(token, db_id, cfg["groups_registry"], cfg)
        return
    _, _, group, url, status = sys.argv[:5]
    notes = sys.argv[5] if len(sys.argv) > 5 else ""
    upsert(token, db_id, group, url, status, notes)


if __name__ == "__main__":
    main()

"""Push new candidates to a Notion database under the Sublease Automation page.

Needs NOTION_TOKEN in the environment (run.sh sources .env). On first run,
creates a candidates database (title: notion.candidates_db_title) under
notion.parent_page_id from groups.yaml and remembers its id in the state file
(notion.state_file, default cache/notion_state.json), so each sublease window
gets its own board. After that, adds
one page per new candidate (keyed by post URL). Existing pages are never
modified, so your Status edits in Notion are safe.

Skips silently when NOTION_TOKEN is unset.
"""
import csv
import json
import os
import time
import urllib.error
import urllib.request

from .common import ROOT, OUT_DIR, CACHE_DIR, POSTS_PATH, load_config, log, read_jsonl
from .instagram import handles

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
STATE_PATH = CACHE_DIR / "notion_state.json"  # rebound per window in main()

DB_PROPERTIES = {
    "Name": {"title": {}},
    "Tier": {"select": {"options": [
        {"name": "A", "color": "green"},
        {"name": "B", "color": "blue"},
        {"name": "C", "color": "gray"},
        {"name": "D", "color": "red"},
    ]}},
    "Tier Reason": {"rich_text": {}},
    "Gender": {"select": {}},
    "Gender Source": {"select": {}},
    # Status is the one field that says what happens next with a person.
    # New -> DM'd/Commented -> Replied -> Ruled Out. Nothing else tracks
    # outreach state: no local ledger, no Active flag. Notion is the record.
    "Status": {"select": {"options": [
        {"name": "New", "color": "blue"},
        {"name": "DM'd", "color": "yellow"},
        {"name": "Commented", "color": "orange"},
        {"name": "Replied", "color": "green"},
        {"name": "Ruled Out", "color": "red"},
    ]}},
    "Days": {"number": {}},
    "Fit": {"select": {}},
    "Wants Start": {"date": {}},
    "Wants End": {"date": {}},
    "Budget": {"rich_text": {}},
    "Term": {"select": {}},
    "Posted": {"date": {}},
    "Instagram": {"rich_text": {}},
    "Group": {"select": {}},
    "Confidence": {"select": {}},
    "Post": {"url": {}},
    "Profile": {"url": {}},
    "Person": {"rich_text": {}},
    "Key": {"rich_text": {}},
}


def api(token, method, path, body=None):
    req = urllib.request.Request(
        f"{NOTION_API}{path}",
        data=json.dumps(body).encode() if body else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def migrate_schema(token, db_id):
    """Add any DB_PROPERTIES columns the live database is missing.

    Without this, adding a field to DB_PROPERTIES silently 400s every page
    create against a database made before the field existed.
    """
    try:
        existing = set(api(token, "GET", f"/databases/{db_id}").get("properties", {}))
    except Exception as e:
        log(f"Notion schema check failed: {e}")
        return
    missing = {k: v for k, v in DB_PROPERTIES.items() if k not in existing}
    if missing:
        try:
            api(token, "PATCH", f"/databases/{db_id}", {"properties": missing})
            log(f"Notion schema: added {', '.join(sorted(missing))}")
        except Exception as e:
            log(f"Notion schema migration failed: {e}")
    # NEVER PATCH an existing select property with a replacement options list:
    # Notion drops any option not in the new list AND blanks it on every page
    # that used it (learned 2026-08-11 — wiped 17 statuses). To add an option,
    # merge it into the live options first.


def configure(cfg):
    """Point STATE_PATH at this window's state file and return the notion config."""
    global STATE_PATH
    notion_cfg = cfg.get("notion", {})
    STATE_PATH = CACHE_DIR / notion_cfg.get("state_file", "notion_state.json")
    return notion_cfg


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"database_id": None, "synced_keys": []}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state))


def ensure_database(token, parent_page_id, state, title="Sublease Candidates"):
    if state["database_id"]:
        migrate_schema(token, state["database_id"])
        return state["database_id"]
    result = api(token, "POST", "/databases", {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": DB_PROPERTIES,
    })
    state["database_id"] = result["id"]
    save_state(state)
    log(f"Created Notion database '{title}' ({result['id']})")
    return result["id"]


def fetch_statuses(token, db_id):
    """{person_key or post_url or name: Status} straight off the board.

    Notion is the only record of who has been contacted and where they got to,
    so the pipeline asks it rather than keeping a second copy locally.
    """
    out, cursor = {}, None
    while True:
        body = {"page_size": 100, **({"start_cursor": cursor} if cursor else {})}
        page = api(token, "POST", f"/databases/{db_id}/query", body)
        for pg in page["results"]:
            pr = pg["properties"]
            status = (pr.get("Status", {}).get("select") or {}).get("name")
            if not status:
                continue
            txt = lambda k: "".join(t["plain_text"] for t in pr.get(k, {}).get("rich_text", []))
            for ident in (txt("Person"), txt("Key"),
                          "".join(t["plain_text"] for t in pr["Name"]["title"]).strip().lower()):
                if ident:
                    out.setdefault(ident, status)
        if not page.get("has_more"):
            break
        cursor = page["next_cursor"]
    return out


def rich(text):
    return [{"type": "text", "text": {"content": (text or "")[:1900]}}] if text else []


def sel(value):
    # Notion select options cannot contain commas — strip them.
    if not value:
        return {"select": None}
    name = str(value).replace(",", "")[:95]
    return {"select": {"name": name}}


def candidate_page(cand, full_text=None):
    ig = handles(full_text or cand.get("post_text") or "")
    props = {
        "Name": {"title": rich(cand["name"] or "Unknown")},
        "Status": {"select": {"name": "New"}},
        "Tier": sel(cand.get("tier")),
        "Tier Reason": {"rich_text": rich(cand.get("tier_reason"))},
        "Gender": sel(cand.get("likely_gender") or cand.get("gender")),
        "Gender Source": sel(cand.get("gender_basis")),
        "Days": {"number": int(cand["days_covered"] or 0)},
        "Fit": sel(cand["fit"]),
        "Group": sel(cand["group"]),
        "Confidence": sel(cand["confidence"]),
        "Budget": {"rich_text": rich(cand["budget"])},
        "Term": sel(cand.get("term")),
        "Instagram": {"rich_text": rich(" ".join("@" + h for h in ig[:3]))},
        "Post": {"url": cand["post_url"] or None},
        "Profile": {"url": cand["profile_url"] or None},
        "Person": {"rich_text": rich(cand.get("person_key") or "")},
        "Key": {"rich_text": rich(sync_key(cand))},
    }
    if cand["wants_start"]:
        props["Wants Start"] = {"date": {"start": cand["wants_start"]}}
    if cand["wants_end"]:
        props["Wants End"] = {"date": {"start": cand["wants_end"]}}
    if cand.get("post_date"):
        props["Posted"] = {"date": {"start": str(cand["post_date"])[:10]}}

    children = []
    if full_text or cand.get("post_text"):
        children.append({"object": "block", "type": "paragraph",
                         "paragraph": {"rich_text": rich(full_text or cand["post_text"])}})
    if cand.get("draft_message"):
        children.append({"object": "block", "type": "callout",
                         "callout": {"icon": {"type": "emoji", "emoji": "✉️"},
                                     "rich_text": rich(cand["draft_message"])}})
    return props, children


def sync_key(cand):
    return cand.get("post_url") or f"{cand.get('name')}|{cand.get('wants_start')}|{cand.get('wants_end')}"


def main():
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        log("Notion sync skipped: NOTION_TOKEN not set")
        return

    notion_cfg = configure(load_config())
    title = notion_cfg.get("candidates_db_title", "Sublease Candidates")
    parent = str(notion_cfg.get("people_page_id")
                 or notion_cfg.get("parent_page_id", "")).replace("-", "")
    if not parent:
        log("Notion sync skipped: notion.parent_page_id not set in groups.yaml")
        return

    csv_path = OUT_DIR / "candidates.csv"
    if not csv_path.exists():
        log("Notion sync skipped: no candidates.csv yet")
        return

    state = load_state()
    try:
        db_id = ensure_database(token, parent, state, title)
    except urllib.error.HTTPError as e:
        log(f"Notion ERROR creating database: {e.code} {e.read().decode()[:300]}")
        return

    with open(csv_path) as f:
        candidates = list(csv.DictReader(f))

    synced = set(state["synced_keys"])
    new = [c for c in candidates if sync_key(c) not in synced]
    if not new:
        log("Notion sync: nothing new")
        return

    full_text = {p.get("url"): p.get("text") for p in read_jsonl(POSTS_PATH) if p.get("url")}
    created = 0
    for cand in new:
        props, children = candidate_page(cand, full_text.get(cand.get("post_url")))
        try:
            api(token, "POST", "/pages", {
                "parent": {"database_id": db_id},
                "properties": props,
                "children": children,
            })
            synced.add(sync_key(cand))
            created += 1
        except urllib.error.HTTPError as e:
            log(f"Notion ERROR for {cand.get('name')}: {e.code} {e.read().decode()[:200]}")
        time.sleep(0.4)  # stay under Notion's ~3 req/s limit

    state["synced_keys"] = sorted(synced)
    save_state(state)
    log(f"Notion sync: {created} new candidate(s) pushed")


if __name__ == "__main__":
    main()

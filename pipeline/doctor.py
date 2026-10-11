"""Check that everything this repo needs is actually connected.

Read-only and free: no model call, no Notion write, no scrape. Run it on a
fresh checkout, after editing config.yaml, and any time something stops
working — a Facebook session expires every few weeks and the symptom is an
empty scrape, not an error.

Each line is a check. BLOCKERs stop the pipeline; warnings only cost you
features. The exit code is 1 if any blocker failed, so a script can gate on it.

Usage: python -m pipeline.doctor
"""
import importlib.util
import json
import os
import shutil
import sys
import urllib.error
from datetime import date, datetime
from pathlib import Path

from .common import CACHE_DIR, ROOT, config_path, log

OK, BAD, WARN, INFO = "  ok  ", " FAIL ", " warn ", "  --  "
_results = []


def check(label, state, detail="", fix=""):
    _results.append((state, label))
    line = f"[{state}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    if fix and state in (BAD, WARN):
        print(f"         fix: {fix}")


def _notion(token, path):
    from .notion_push import api
    return api(token, "GET", path)


# --------------------------------------------------------------------------
def check_python():
    v = sys.version_info
    ok = v >= (3, 10)
    check("Python 3.10+", OK if ok else BAD, f"running {v.major}.{v.minor}.{v.micro}")


def check_deps():
    for mod, why, blocker in (("yaml", "config and registry parsing", True),
                              ("forage", "Facebook scraping", False)):
        found = importlib.util.find_spec(mod) is not None
        check(f"{mod} installed", OK if found else (BAD if blocker else WARN), why,
              ".venv/bin/pip install -r requirements.txt")


def check_claude_cli():
    path = shutil.which("claude")
    check("claude CLI on PATH", OK if path else BAD,
          path or "extraction and gender labelling call `claude -p`",
          "install Claude Code: https://claude.com/claude-code")


def check_config():
    try:
        cfg_file = config_path()
    except SystemExit:
        check("config.yaml", BAD, "not found",
              "cp config.example.yaml config.yaml, then edit it")
        return None
    from .common import load_config
    try:
        cfg = load_config()
    except Exception as e:
        check("config.yaml parses", BAD, str(e)[:90], "check the YAML indentation")
        return None
    check("config.yaml", OK, cfg_file.name)

    w = cfg["window"]
    nights = (w["end"] - w["start"]).days
    if nights <= 0:
        check("window", BAD, f"{w['start']} to {w['end']} is {nights} nights",
              "window.end must be after window.start")
    elif w["start"] < date.today():
        check("window", WARN, f"{w['start']} to {w['end']} already started",
              "set window to the dates your place is actually free")
    else:
        check("window", OK, f"{w['start']} to {w['end']} ({nights} nights)")

    rate = cfg.get("listing", {}).get("nightly_rate")
    check("listing.nightly_rate", OK if rate else WARN,
          f"${rate} a night" if rate else "not set; replies can't quote a price",
          "set listing.nightly_rate in config.yaml")

    prefer = cfg.get("preferences", {}).get("prefer_gender", "none")
    check("preferences.prefer_gender", INFO,
          "none — gender is labelled and changes no ranking" if prefer == "none"
          else f"{prefer} — a match ranks up, the opposite is held back from outreach")
    return cfg


def check_notion(cfg):
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        check("NOTION_TOKEN", BAD, ".env missing or has no NOTION_TOKEN",
              "cp .env.example .env and paste your integration token")
        return
    try:
        me = _notion(token, "/users/me")
        check("NOTION_TOKEN", OK, f"authenticated as {me.get('name') or me.get('id')}")
    except urllib.error.HTTPError as e:
        check("NOTION_TOKEN", BAD, f"Notion rejected it ({e.code})",
              "check the token at https://www.notion.so/my-integrations")
        return
    except Exception as e:
        check("NOTION_TOKEN", BAD, f"could not reach Notion: {str(e)[:60]}")
        return

    ncfg = (cfg or {}).get("notion", {})
    for key, what in (("parent_page_id", "parent page"),
                      ("people_page_id", "People board page"),
                      ("posts_page_id", "Posts board page")):
        raw = str(ncfg.get(key) or "").replace("-", "")
        if not raw:
            check(f"notion.{key}", WARN, f"not set ({what})",
                  "paste the 32-hex id from the page URL into config.yaml")
            continue
        try:
            page = _notion(token, f"/pages/{raw}")
            title = "".join(
                t.get("plain_text", "")
                for prop in page.get("properties", {}).values()
                if prop.get("type") == "title" for t in prop.get("title", []))
            check(f"notion.{key}", OK, f'shared with the integration — "{title or what}"')
        except urllib.error.HTTPError as e:
            hint = ("open the page in Notion, ••• -> Connections -> add your integration"
                    if e.code == 404 else "")
            check(f"notion.{key}", BAD, f"Notion says {e.code} for {what}", hint)

    state_file = ncfg.get("state_file", "notion_state.json")
    state_path = CACHE_DIR / state_file
    if not state_path.exists():
        check("Notion databases", INFO,
              "not created yet; the first ./run.sh creates them under those pages")
        return
    state = json.loads(state_path.read_text())
    for key, label in (("database_id", "People database"),
                       ("posts_database_id", "Posts database")):
        db = state.get(key)
        if not db:
            check(label, INFO, "not created yet")
            continue
        try:
            _notion(token, f"/databases/{db}")
            # Notion ids are time-ordered, so two boards made seconds apart share
            # a prefix; show the tail too or they look like the same database.
            short = f"{db[:8]}…{db[-4:]}"
            check(label, OK, f"live ({short}), {len(state.get('synced_keys', []))} "
                             f"cards synced" if key == "database_id" else f"live ({short})")
        except urllib.error.HTTPError as e:
            check(label, BAD, f"id in {state_file} returns {e.code}",
                  f"delete cache/{state_file} to start a fresh board for this window")


def check_registry(cfg):
    import yaml
    path = Path(str((cfg or {}).get("groups_registry", "groups/nyc.yaml"))).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        check("group registry", BAD, f"{path.name} not found",
              "cp groups/nyc.example.yaml groups/nyc.yaml")
        return
    groups = yaml.safe_load(path.read_text()).get("groups", [])
    active = [g for g in groups if g.get("status", "active") == "active"]
    readable = [g for g in active if g.get("read") and g.get("id")]
    postable = [g for g in active if g.get("post") in ("ok", "admin-queue", "untested")]
    check("group registry", OK, f"{path.name}, {len(active)} active groups")
    check("groups to scrape", OK if readable else BAD,
          f"{len(readable)} with read: true",
          "join a group, then set membership: member and read: true on its entry")
    check("groups to post in", OK if postable else WARN,
          f"{len(postable)} postable",
          "set post: untested on groups you are a member of")


def check_facebook_session():
    try:
        from forage.auth import get_session_path
    except Exception:
        check("Facebook session", WARN, "forage not installed, cannot check")
        return
    path = Path(get_session_path())
    if not path.exists():
        check("Facebook session", BAD, "no saved session",
              ".venv/bin/python fb_login.py (you type your own credentials)")
        return
    age = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).days
    check("Facebook session", OK if age < 21 else WARN,
          f"saved {age} day(s) ago",
          "re-run .venv/bin/python fb_login.py if scrapes come back empty")


def check_listing():
    post = ROOT / "listing_post.txt"
    check("listing_post.txt", OK if post.exists() else WARN,
          f"{len(post.read_text().split())} words" if post.exists()
          else "not written yet; nothing to post in a group",
          "cp listing_post.example.txt listing_post.txt and write your listing")

    photos = ROOT / "listing_photos"
    n = len([p for p in photos.glob("*") if p.suffix.lower()
             in (".jpg", ".jpeg", ".png", ".heic", ".webp")]) if photos.is_dir() else 0
    check("listing photos", OK if n >= 4 else WARN,
          f"{n} image(s) in listing_photos/",
          "add 6-8 photos; posts with photos get far more replies")

    tpl = ROOT / "message_template.txt"
    check("message template", OK, "message_template.txt" if tpl.exists()
          else "using message_template.example.txt")


def main():
    print(f"sublease-hunter doctor — {ROOT}\n")
    check_python()
    check_deps()
    check_claude_cli()
    print()
    cfg = check_config()
    print()
    check_notion(cfg)
    print()
    check_registry(cfg)
    check_facebook_session()
    check_listing()

    fails = [l for s, l in _results if s == BAD]
    warns = [l for s, l in _results if s == WARN]
    print()
    if fails:
        print(f"{len(fails)} blocker(s): {', '.join(fails)}")
    if warns:
        print(f"{len(warns)} warning(s): {', '.join(warns)}")
    if not fails and not warns:
        print("Everything checks out. Next: ./run.sh --fixtures, then ./run.sh")
    elif not fails:
        print("No blockers. The pipeline will run; the warnings above cost you features.")
    print("\nNot checkable from here (the agent checks these): a browser tool for\n"
          "posting and DMs, and a calendar tool for booking calls.")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()

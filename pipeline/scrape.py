"""Scrape configured groups: ForageFacebook for private, Apify actor for public.

Normalizes every post to {id, url, group, author_name, author_url, posted_at, text}
and appends only unseen posts to cache/posts.jsonl.
"""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from .common import ROOT, RAW_DIR, POSTS_PATH, load_config, log, read_jsonl, append_jsonl

APIFY_ACTOR = "apify~facebook-groups-scraper"
MONITOR_DB = ROOT / "vendor" / "fb-group-monitor" / "data" / "monitor.db"

FB_POST_NUM = re.compile(r"(?:permalink|posts)/(\d+)|story_fbid=(\d+)")


def clean_author_url(url):
    """Make author profile links absolute and strip tracking params."""
    if not url:
        return url
    url = url.split("?")[0]
    if url.startswith("/"):
        url = "https://www.facebook.com" + url
    return url


def canonical_pid(url, fallback):
    """Same FB post scraped by different tools must get the same id."""
    if url:
        m = FB_POST_NUM.search(url)
        if m:
            return f"fbpost:{m.group(1) or m.group(2)}"
    return fallback


def _first(rec: dict, *keys):
    for k in keys:
        v = rec.get(k)
        if v:
            return v
    return None


def normalize(rec: dict, group_name: str, slug: str = None) -> dict:
    text = _first(rec, "text", "post_text", "content", "message", "postText") or ""
    url = _first(rec, "url", "post_url", "postUrl", "link", "topLevelUrl", "facebookUrl")
    if not url and slug and rec.get("id"):
        url = f"https://www.facebook.com/groups/{slug}/posts/{rec['id']}"
    author = rec.get("author") or rec.get("user") or {}
    if isinstance(author, dict):
        author_name = _first(author, "name", "username", "title")
        author_url = _first(author, "url", "profileUrl", "profile_url", "link")
    else:
        author_name, author_url = str(author), None
    author_name = author_name or _first(rec, "author_name", "username", "userName")
    author_url = clean_author_url(author_url or _first(rec, "author_url", "profile_url", "userUrl"))
    posted = _first(rec, "time", "date", "timestamp", "posted_at", "creation_time",
                    "date_posted", "publishedTime")
    pid = canonical_pid(url, url or str(rec.get("id") or "") or
                        hashlib.sha1(f"{group_name}|{author_name}|{text[:200]}".encode()).hexdigest())
    return {
        "id": pid,
        "url": url,
        "group": group_name,
        "author_name": author_name,
        "author_url": author_url,
        "posted_at": str(posted) if posted else None,
        "text": text,
    }


def _load_records(payload) -> list:
    """Forage/Apify output may be a bare list or wrapped in a dict."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("posts", "items", "data", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def scrape_forage(group: dict, settings: dict) -> list:
    slug = str(group["slug"])
    outfile = RAW_DIR / f"{slug}.json"
    forage_bin = Path(sys.executable).parent / "forage"
    cmd = [
        str(forage_bin), "scrape", slug,
        "--days", str(settings.get("days_back", 21)),
        "--skip-comments",
        "--skip-reactions",
        "--no-input",
        "--delay", str(settings.get("forage_delay", 3.0)),
        "--limit", str(settings.get("limit_per_group", 300)),
        "-f", "json",
        "-o", str(outfile),
    ]
    log(f"  forage: {' '.join(cmd)}")
    timeout = int(float(settings.get("group_timeout_min", 25)) * 60)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # One group that never reaches its date cutoff must not sink the run.
        log(f"  ERROR scraping {group['name']}: timed out after {timeout // 60} min, skipped")
        return []
    if result.returncode != 0:
        log(f"  ERROR scraping {group['name']}: {result.stderr.strip()[:500]}")
        return []
    try:
        payload = json.loads(outfile.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log(f"  ERROR reading forage output for {group['name']}: {e}")
        return []
    return [normalize(r, group["name"], slug) for r in _load_records(payload)]


def load_cached_raw(group: dict, max_age_hours: float):
    """Posts from raw/<slug>.json if it was scraped within max_age_hours, else None."""
    slug = str(group["slug"])
    outfile = RAW_DIR / f"{slug}.json"
    if not outfile.exists() or time.time() - outfile.stat().st_mtime > max_age_hours * 3600:
        return None
    try:
        payload = json.loads(outfile.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return [normalize(r, group["name"], slug) for r in _load_records(payload)]


def scrape_apify(group: dict, settings: dict, token: str) -> list:
    group_url = f"https://www.facebook.com/groups/{group['slug']}"
    body = json.dumps({
        "startUrls": [{"url": group_url}],
        "resultsLimit": settings.get("limit_per_group", 300),
        "viewOption": "CHRONOLOGICAL",
    }).encode()
    api = (f"https://api.apify.com/v2/acts/{APIFY_ACTOR}"
           f"/run-sync-get-dataset-items?timeout=280&format=json")
    req = urllib.request.Request(api, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    })
    log(f"  apify: {group_url}")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            payload = json.loads(resp.read())
    except Exception as e:
        log(f"  ERROR from Apify for {group['name']}: {e}")
        return []
    return [normalize(r, group["name"]) for r in _load_records(payload)]


def ingest_monitor_db(cfg: dict) -> list:
    """Harvest posts collected by the vendored fb-group-monitor, if it's in use.

    Dormant by default: no-op until vendor/fb-group-monitor/data/monitor.db exists.
    """
    if not MONITOR_DB.exists():
        return []
    slug_to_name = {str(g["slug"]): g["name"] for g in cfg.get("groups", [])}
    conn = sqlite3.connect(str(MONITOR_DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT post_id, group_url, author, author_url, post_url, text, timestamp FROM posts"
        ).fetchall()
    except sqlite3.Error as e:
        log(f"  ERROR reading monitor db: {e}")
        return []
    finally:
        conn.close()

    posts = []
    for row in rows:
        rec = dict(row)
        rec["id"] = rec.pop("post_id")
        group_url = rec.get("group_url") or ""
        name = next((n for s, n in slug_to_name.items() if s in group_url), group_url)
        posts.append(normalize(rec, name))
    return posts


def ingest_fixtures() -> list:
    """Sample posts, for exercising the pipeline without touching Facebook.

    Their timestamps are rewritten to the last few days on the way in: the
    ranker drops anything older than settings.max_post_age_days, so a fixture
    file with fixed dates would quietly produce zero candidates a month after
    it was written. The `_case` key on each fixture says what it is there to
    test and is ignored by everything downstream.
    """
    payload = json.loads((ROOT / "fixtures" / "posts.json").read_text())
    today = date.today()
    out = []
    for i, rec in enumerate(payload):
        rec = {k: v for k, v in rec.items() if k != "_case"}
        rec["time"] = (today - timedelta(days=i % 5 + 1)).isoformat()
        out.append(normalize(rec, rec.get("group", "Fixture Group")))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", action="store_true",
                        help="ingest fixtures/posts.json instead of scraping")
    parser.add_argument("--days", type=int, default=None,
                        help="override days_back (scheduled runs use 3 for light scrapes)")
    parser.add_argument("--group", default=None,
                        help="only scrape groups whose slug or name contains this string")
    parser.add_argument("--rotate", type=int, default=None,
                        help="scrape only the N least-recently-scraped groups "
                             "(keeps a scheduled run bounded; rotates coverage)")
    parser.add_argument("--limit", type=int, default=None,
                        help="override limit_per_group (caps scrape time on huge groups)")
    parser.add_argument("--resume-hours", type=float, default=None,
                        help="reuse raw/<slug>.json for groups scraped within N hours")
    parser.add_argument("--cached-only", action="store_true",
                        help="with --resume-hours: ingest fresh raw files, scrape nothing")
    args = parser.parse_args()

    cfg = load_config()
    settings = cfg.get("settings", {})
    if args.days:
        settings["days_back"] = args.days
    if args.limit:
        settings["limit_per_group"] = args.limit
    seen = {p["id"] for p in read_jsonl(POSTS_PATH)}
    RAW_DIR.mkdir(exist_ok=True)

    posts = []
    new_count = 0
    if args.fixtures:
        posts = ingest_fixtures()
    else:
        token = os.environ.get("APIFY_TOKEN")
        groups = cfg["groups"]
        if args.group:
            needle = args.group.lower()
            groups = [g for g in groups
                      if needle in str(g["slug"]).lower() or needle in g["name"].lower()]
            if not groups:
                log(f"No group matching '{args.group}' in groups.yaml")
        if args.rotate:
            # Oldest raw file first, so every group comes round over a few runs.
            def last_scraped(g):
                f = RAW_DIR / f"{g['slug']}.json"
                return f.stat().st_mtime if f.exists() else 0
            groups = sorted(groups, key=last_scraped)[:args.rotate]
            log(f"Rotating: this run covers {', '.join(g['name'][:28] for g in groups)}")
        for group in groups:
            cached = (load_cached_raw(group, args.resume_hours)
                      if args.resume_hours is not None else None)
            if cached is not None:
                log(f"Reusing {group['name']}: {len(cached)} posts from recent raw file")
                got = cached
            elif args.cached_only:
                continue
            else:
                log(f"Scraping {group['name']} ({group['method']})")
                if group["method"] == "forage":
                    got = scrape_forage(group, settings)
                elif group["method"] == "apify":
                    if not token:
                        log("  skipped: APIFY_TOKEN not set")
                        continue
                    got = scrape_apify(group, settings, token)
                else:
                    continue
            # Save per group so a later failure can't lose what's already scraped.
            fresh = [p for p in got if p["id"] not in seen and p["text"].strip()]
            append_jsonl(POSTS_PATH, fresh)
            seen.update(p["id"] for p in fresh)
            new_count += len(fresh)
            posts.extend(got)
        monitor_posts = ingest_monitor_db(cfg)
        if monitor_posts:
            log(f"Ingested {len(monitor_posts)} posts from fb-group-monitor db")
            posts.extend(monitor_posts)

    fresh = [p for p in posts if p["id"] not in seen and p["text"].strip()]
    append_jsonl(POSTS_PATH, fresh)
    log(f"Scraped {len(posts)} posts, {new_count + len(fresh)} new -> {POSTS_PATH}")


if __name__ == "__main__":
    main()

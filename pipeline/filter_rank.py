"""Filter extracted seekers to the availability window, rank, and emit CSVs.

Outputs:
  out/candidates.csv      all matching candidates, ranked (rebuilt each run)
  out/new_candidates.csv  candidates first seen this run
  out/coverage_report.md  best single candidates + complementary pairs
"""
import csv
import json
import re
from datetime import date, timedelta
from itertools import combinations

from .common import (ROOT, OUT_DIR, POSTS_PATH, EXTRACTED_PATH, CACHE_DIR,
                     load_config, log, read_jsonl)

REPORTED_PATH = CACHE_DIR / "reported_ids.json"

CSV_COLUMNS = [
    "rank", "tier", "tier_reason", "fit", "days_covered", "wants_start", "wants_end",
    "name", "occupants", "gender", "profile_url", "post_url", "group", "post_date",
    "budget", "confidence", "term", "likely_gender", "gender_basis",
    "status", "person_key",
    "draft_message", "date_text", "post_text",
]

# Household tiering. This is a PRIVATE ranking signal for your own shortlist —
# it never appears in the public listing post. Rules:
#   - Two people sharing the one room is a dealbreaker (a couple in one room).
#     Note: someone who needs TWO SEPARATE rooms is fine — only one of them
#     would take this room.
#   - If config sets preferences.prefer_gender, a match ranks a notch higher and
#     the opposite ranks a notch lower. Nobody is excluded by it; with the
#     default ("none") gender is recorded and changes no score.
TIER_LABELS = {1: "A", 2: "B", 3: "C"}


# Someone who needs a place weeks before the room frees up has to find
# something else first, so they rank as a long shot however well they "cover".
EARLY_START_GRACE = timedelta(days=14)


def starts_too_early(cand, w_start):
    return bool(w_start and cand.get("wants_start")
                and cand["wants_start"] < w_start - EARLY_START_GRACE)


def tier_for(cand, window_days, w_start=None, prefer_gender="none"):
    """Return (tier_label, reason). A is the best match."""
    days = cand["days_covered"]
    coverage = days / window_days if window_days else 0

    if (cand.get("people_in_one_room") or 1) >= 2:
        return "D", "two people sharing one room — household dealbreaker"

    if coverage >= 0.9:
        base, bits = 1, [f"covers {days}/{window_days} days"]
    elif coverage >= 0.6:
        base, bits = 2, [f"covers {days}/{window_days} days"]
    else:
        base, bits = 3, [f"covers only {days}/{window_days} days"]

    gender = cand.get("gender")
    if prefer_gender in ("male", "female") and gender in ("male", "female"):
        if gender == prefer_gender:
            bits.append(f"{gender} (household preference)")
        else:
            base = min(base + 1, 3)
            bits.append(f"{gender} (fine, ranked just below)")
    elif gender:
        bits.append(gender)
    else:
        bits.append("gender unstated")

    if cand.get("wants_multiple_rooms"):
        bits.append("needs 2 rooms, one person would take yours")

    # Open-ended "from Nov 1, long term" scores as full coverage, but someone
    # hunting a yearly lease rarely takes a few-week sublet.
    if cand.get("term") == "long":
        base = 3
        bits.append("wants long-term lease (unlikely to take a short sublet)")

    if starts_too_early(cand, w_start):
        base = 3
        bits.append(f"needs a place from {fmt(cand['wants_start'])}, "
                    f"before the room is free ({fmt(w_start)})")

    return TIER_LABELS[base], "; ".join(bits)


PROFILE_UID = re.compile(r"/user/(\d+)")


def person_key(cand):
    """One key per human. The Facebook user id in the profile URL survives
    cross-posting and reposting; the display name is only a fallback."""
    m = PROFILE_UID.search(cand.get("profile_url") or "")
    return f"fb:{m.group(1)}" if m else "name:" + (cand.get("name") or "").strip().lower()


def _gender_label(stated, author_name, name_gender):
    """Best-known gender plus where it came from. Labels only, never filters."""
    if stated:
        return {"likely_gender": stated, "gender_basis": "stated"}
    first = (author_name or "").strip().split()
    guess = name_gender.get(first[0].lower()) if first else None
    if guess and guess.get("gender") in ("male", "female"):
        return {"likely_gender": guess["gender"],
                "gender_basis": f"name ({guess.get('confidence', '?')})"}
    if guess:
        return {"likely_gender": guess["gender"], "gender_basis": "name"}
    return {"likely_gender": "unknown", "gender_basis": ""}


def parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def classify(start, end, w_start, w_end):
    """Return (fit, days_covered) for a requested range vs the window."""
    if start is None and end is None:
        return None, 0
    start = start or w_start          # open start: assume flexible from window start
    end = end or w_end                # open end ("flexible"): could run to window end
    if end < start:
        start, end = end, start
    overlap_start = max(start, w_start)
    overlap_end = min(end, w_end)
    days = (overlap_end - overlap_start).days + 1
    if days <= 0:
        return None, 0
    if start >= w_start and end <= w_end:
        fit = "full-window" if days >= (w_end - w_start).days + 1 else "inside"
    elif start <= w_start and end >= w_end:
        fit = "wants-more"            # covers the whole window but extends beyond
    else:
        fit = "overlap"               # spills outside the window on one side
    return fit, days


def fmt(d):
    return d.strftime("%b %-d") if d else "?"


def build_draft(template, cand, listing=None, window=None):
    first = (cand["name"] or "there").split()[0]
    start, end = cand["wants_start"], cand["wants_end"]
    if start and end:
        their_dates = f"{fmt(start)} – {fmt(end)}"
    elif start:
        their_dates = f"from {fmt(start)}"
    else:
        their_dates = f"until {fmt(end)}"
    listing = listing or {}
    # {area} and {window} come from config so one template works for any letting
    # period: change the dates in config.yaml and every draft follows.
    text = (template
            .replace("{first_name}", first)
            .replace("{their_dates}", their_dates)
            .replace("{group}", cand["group"] or "the group")
            .replace("{area}", str(listing.get("neighbourhood") or "my"))
            .replace("{window}", f"{fmt(window['start'])} - {fmt(window['end'])}"
                                 if window else ""))
    return sanitize_for_messenger(text)


# Messenger auto-converts some ASCII sequences into emoji — "8)" becomes 😎,
# ":(" becomes a frown, etc. Keep drafts literal by avoiding those sequences.
EMOTICON_TRAPS = {"8)": "8 )", "8-)": "8 )", ":)": ": )", ":(": ": (",
                  ":P": ": P", ":D": ": D", ";)": "; )", ":/": ": /"}


def sanitize_for_messenger(text):
    for trap, safe in EMOTICON_TRAPS.items():
        text = text.replace(trap, safe)
    return text


def main() -> None:
    cfg = load_config()
    w_start, w_end = cfg["window"]["start"], cfg["window"]["end"]
    window_days = (w_end - w_start).days + 1

    posts = {p["id"]: p for p in read_jsonl(POSTS_PATH)}
    extracted = read_jsonl(EXTRACTED_PATH)
    enrichment = {r["id"]: r for r in read_jsonl(CACHE_DIR / "enrichment.jsonl")}
    # Name-based gender labels (pipeline/gender.py). A self-stated gender from
    # enrich.py always wins; this only fills the gaps, and never filters anyone.
    name_gender = {r["name"]: r for r in read_jsonl(CACHE_DIR / "gender.jsonl")}
    # Your own template if you wrote one, otherwise the shipped example, so a
    # fresh checkout ranks without first needing a file that is gitignored.
    tpl = ROOT / "message_template.txt"
    if not tpl.exists():
        tpl = ROOT / "message_template.example.txt"
        log(f"no message_template.txt — drafting from {tpl.name}")
    template = tpl.read_text().strip()

    candidates = []
    # Old posts (e.g. a previous period's scrape still in the cache) are stale
    # leads: the person has almost certainly found a place by now.
    max_age = int(cfg.get("settings", {}).get("max_post_age_days", 40))
    cutoff = (date.today() - timedelta(days=max_age)).isoformat()
    stale = 0
    for rec in extracted:
        if not rec.get("is_seeking"):
            continue
        post = posts.get(rec["id"])
        if not post:
            continue
        if str(post.get("posted_at") or "")[:10] < cutoff:
            stale += 1
            continue
        start, end = parse_date(rec.get("start_date")), parse_date(rec.get("end_date"))
        fit, days = classify(start, end, w_start, w_end)
        if fit is None:
            continue
        enr = enrichment.get(rec["id"], {})
        candidates.append({
            "id": rec["id"],
            "fit": fit,
            "days_covered": days,
            "wants_start": start,
            "wants_end": end,
            "name": post.get("author_name"),
            "profile_url": post.get("author_url"),
            "post_url": post.get("url"),
            "group": post.get("group"),
            "post_date": post.get("posted_at"),
            "budget": rec.get("budget"),
            "confidence": rec.get("confidence"),
            "term": rec.get("term"),
            "date_text": rec.get("date_text"),
            "people_in_one_room": enr.get("people_in_one_room"),
            "wants_multiple_rooms": enr.get("wants_multiple_rooms"),
            "gender": enr.get("gender"),
            **_gender_label(enr.get("gender"), post.get("author_name"), name_gender),
            "occupants": enr.get("group_size") or enr.get("people_in_one_room") or 1,
            "post_text": (post.get("text") or "")[:500].replace("\n", " "),
        })

    # Same person cross-posts to several groups and reposts for reach. Collapse
    # to ONE row per human, keyed on their Facebook user id, which is stable
    # across groups and reposts.
    #
    # This used to key on (name, wants_start, wants_end), which split a person
    # whenever two of their posts worded dates differently: Ben Lee said "Dec 7"
    # in one group and "Dec 10" in another and became two candidates, each
    # separately DM-able and each with its own Notion card. 434 rows covered
    # only 389 people, and that is how the same person got messaged twice.
    # Keep the row with the best coverage, breaking ties on the newest post.
    candidates.sort(key=lambda c: (-int(c["days_covered"] or 0),
                                   str(c["post_date"] or "")[:19]),
                    reverse=False)
    seen_people = {}
    for cand in candidates:
        key = person_key(cand)
        if key not in seen_people:
            seen_people[key] = cand
        elif cand["group"] and cand["group"] != seen_people[key]["group"]:
            seen_people[key].setdefault("also_posted_in", []).append(cand["group"])
    candidates = list(seen_people.values())

    for cand in candidates:
        cand["tier"], cand["tier_reason"] = tier_for(
            cand, window_days, w_start,
            cfg.get("preferences", {}).get("prefer_gender", "none"))

    # Who has been contacted, and how far they got, comes from Notion. The
    # Status column is the only record; there is deliberately no local copy.
    statuses = {}
    try:
        import os
        from . import notion_push
        token = os.environ.get("NOTION_TOKEN")
        if token:
            notion_push.configure(cfg)
            db_id = notion_push.load_state().get("database_id")
            if db_id:
                statuses = notion_push.fetch_statuses(token, db_id)
    except Exception as e:
        log(f"  could not read Notion statuses ({e}); treating everyone as New")
    for cand in candidates:
        key = person_key(cand)
        cand["person_key"] = key
        cand["status"] = (statuses.get(key)
                          or statuses.get(cand.get("post_url") or "")
                          or statuses.get((cand.get("name") or "").strip().lower())
                          or "New")

    fit_order = {"full-window": 0, "inside": 1, "wants-more": 2, "overlap": 3}
    tier_order = {"A": 0, "B": 1, "C": 2, "D": 3}
    candidates.sort(key=lambda c: str(c["post_date"] or ""), reverse=True)
    candidates.sort(key=lambda c: (tier_order.get(c["tier"], 9), -c["days_covered"],
                                   fit_order.get(c["fit"], 9)))

    previously = set()
    if REPORTED_PATH.exists():
        previously = set(json.loads(REPORTED_PATH.read_text()))
    new_ids = [c["id"] for c in candidates if c["id"] not in previously]

    OUT_DIR.mkdir(exist_ok=True)
    for path, rows in [(OUT_DIR / "candidates.csv", candidates),
                       (OUT_DIR / "new_candidates.csv",
                        [c for c in candidates if c["id"] in set(new_ids)])]:
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for i, cand in enumerate(rows, 1):
                row = dict(cand)
                row["rank"] = i
                row["wants_start"] = cand["wants_start"].isoformat() if cand["wants_start"] else ""
                row["wants_end"] = cand["wants_end"].isoformat() if cand["wants_end"] else ""
                row["draft_message"] = build_draft(
                    template, cand, cfg.get("listing"), cfg["window"])
                writer.writerow(row)

    # The outreach shortlist: good fits whose Notion Status is still New.
    # Reading this instead of candidates.csv makes a double-text impossible.
    todo = [c for c in candidates
            if c["tier"] in ("A", "B") and c["status"] == "New"]
    with open(OUT_DIR / "to_contact.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for i, cand in enumerate(todo, 1):
            row = dict(cand)
            row["rank"] = i
            row["wants_start"] = cand["wants_start"].isoformat() if cand["wants_start"] else ""
            row["wants_end"] = cand["wants_end"].isoformat() if cand["wants_end"] else ""
            row["draft_message"] = build_draft(
                    template, cand, cfg.get("listing"), cfg["window"])
            writer.writerow(row)
    log(f"{len(todo)} tier A/B still to contact -> {OUT_DIR / 'to_contact.csv'}")

    REPORTED_PATH.write_text(json.dumps(sorted(previously | set(new_ids))))
    write_coverage_report(candidates, w_start, w_end, window_days)

    log(f"{len(candidates)} candidates ({len(new_ids)} new) -> {OUT_DIR / 'candidates.csv'}"
        f" ({stale} seekers skipped: posted before {cutoff})")


def write_coverage_report(candidates, w_start, w_end, window_days):
    lines = [f"# Coverage report — window {w_start} to {w_end} ({window_days} days)\n"]

    def span(c):
        return f"{c['wants_start'] or 'open'} – {c['wants_end'] or 'open'}"

    # Only realistic people: no household dealbreakers, nobody who needs a
    # place weeks before the room frees up.
    viable = [c for c in candidates
              if c["tier"] != "D" and not starts_too_early(c, w_start)]
    singles = [c for c in viable if c["days_covered"] >= window_days - 2]
    lines.append(f"## Near-complete singles ({len(singles)})\n")
    for c in singles[:10]:
        lines.append(f"- **{c['name']}** wants {span(c)} "
                     f"({c['days_covered']}/{window_days} days, {c['fit']}) — {c['post_url'] or c['group']}")

    partials = [c for c in viable if c["days_covered"] < window_days - 2]
    # One room hosts one person at a time, so a pair must be sequential: their
    # in-window ranges may overlap by at most a short handoff.
    max_overlap = 3

    def in_window(c):
        start = max(c["wants_start"] or w_start, w_start)
        end = min(c["wants_end"] or w_end, w_end)
        return {start + timedelta(days=i) for i in range((end - start).days + 1)}

    pairs = []
    for a, b in combinations(partials, 2):
        da, db = in_window(a), in_window(b)
        if len(da & db) > max_overlap:
            continue
        pairs.append((len(da | db), a, b))
    pairs.sort(key=lambda t: -t[0])

    lines.append(f"\n## Best back-to-back pairs (overlap ≤ {max_overlap} days)\n")
    for total, a, b in pairs[:5]:
        lines.append(f"- {total}/{window_days} days: **{a['name']}** ({span(a)}) "
                     f"+ **{b['name']}** ({span(b)})")

    (OUT_DIR / "coverage_report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

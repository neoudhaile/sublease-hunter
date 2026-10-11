"""Pull Instagram handles out of candidate posts.

Many seekers say "dm me on insta @handle" — those are reachable even when
Facebook's message-request limit is hit. Usage: python -m pipeline.instagram
"""
import csv
import re

from .common import OUT_DIR, POSTS_PATH, read_jsonl

PAT_URL = re.compile(r"instagram\.com/([A-Za-z0-9._]{3,30})", re.I)
# People write it every which way: "Insta @ handle", "instagram - handle",
# "IG: handle", "@handle". Allow an optional @ AND surrounding whitespace.
PAT_CTX = re.compile(r"(?:insta(?:gram)?|ig)\b[\s:\-–—>]{0,6}@?\s{0,2}([A-Za-z0-9._]{3,30})", re.I)
PAT_AT = re.compile(r"(?<![A-Za-z0-9._/])@\s?([A-Za-z0-9._]{3,30})")
STOP = {"gmail", "yahoo", "hotmail", "icloud", "outlook", "com", "me", "if",
        "the", "and", "dm", "insta", "instagram"}


def handles(text):
    found = []
    for m in PAT_URL.findall(text) + PAT_CTX.findall(text) + PAT_AT.findall(text):
        h = m.strip("._").lower()
        if h in STOP or len(h) < 3 or h.isdigit():
            continue
        if h not in found:
            found.append(h)
    return found


def main():
    by_url, by_name = {}, {}
    for p in read_jsonl(POSTS_PATH):
        if p.get("url"):
            by_url[p["url"].rstrip("/")] = p
        if p.get("author_name"):
            by_name.setdefault(p["author_name"].strip().lower(), p)

    rows = list(csv.DictReader(open(OUT_DIR / "candidates.csv")))
    results = []
    for r in rows:
        post = (by_url.get((r["post_url"] or "").rstrip("/"))
                or by_name.get((r["name"] or "").strip().lower()))
        text = (post or {}).get("text") or r["post_text"]
        if not re.search(r"insta|@", text, re.I):
            continue
        hs = handles(text)
        if hs:
            results.append({
                "tier": r["tier"], "days": int(r["days_covered"]), "name": r["name"],
                "handles": hs, "wants": f"{r['wants_start']} to {r['wants_end'] or 'open'}",
                "budget": r["budget"], "post_url": r["post_url"],
            })

    results.sort(key=lambda x: (x["tier"], -x["days"]))
    out_path = OUT_DIR / "instagram_handles.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["tier", "days", "name", "handles",
                                          "wants", "budget", "post_url"])
        w.writeheader()
        for r in results:
            w.writerow({**r, "handles": " ".join("@" + h for h in r["handles"])})

    print(f"{len(results)} candidates with Instagram handles -> {out_path}\n")
    for r in results:
        hs = " ".join("@" + h for h in r["handles"][:2])
        print(f"[{r['tier']}] {r['days']:>2}d {r['name'][:24]:<24} {hs:<22} {r['wants']}")


if __name__ == "__main__":
    main()

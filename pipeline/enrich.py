"""Enrichment pass: re-read cached listing text to add household-fit fields.

Adds only the NEW fields (occupancy / gender / multi-room) to cache/enrichment.jsonl,
keyed by post id. Date extraction in extracted.jsonl is left untouched, so this
never redoes work and never races with a running extract.
"""
import json
import subprocess

from .common import (CACHE_DIR, POSTS_PATH, EXTRACTED_PATH, load_config, log,
                     read_jsonl, append_jsonl)

ENRICHED_PATH = CACHE_DIR / "enrichment.jsonl"

PROMPT_HEADER = """\
You read NYC housing posts from people SEEKING a place, and extract who would
actually move in. For each post return an object with:
- "id": copied verbatim from the input
- "people_in_one_room": how many people would SHARE A SINGLE ROOM. A couple, or
  two people who explicitly want to live together in one room = 2. A solo
  searcher = 1. CRITICAL: someone looking for TWO SEPARATE ROOMS or a 2-bedroom
  for themselves + a friend is 1 PER ROOM — return 1 for them, and set
  "wants_multiple_rooms": true.
- "wants_multiple_rooms": true if they need 2+ separate rooms/bedrooms
- "group_size": total people who would move in (1 for solo, 2 for a couple or pair)
- "gender": "male" | "female" | null — ONLY when clearly stated or unambiguous
  from self-description ("I'm a 23 year old guy", "she/her", "girl looking").
  NEVER guess from the person's name. Use null when unclear.

Return ONLY a JSON array, one object per post, same order as input. No prose.

POSTS:
"""


def call_claude(posts, model):
    payload = [{"id": p["id"], "text": p["text"][:1200]} for p in posts]
    result = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "text"],
        input=PROMPT_HEADER + json.dumps(payload, ensure_ascii=False),
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed: {result.stderr.strip()[:200]}")
    text = result.stdout
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON array: {text[:150]}")
    parsed = json.loads(text[start:end + 1])
    if len(parsed) != len(posts):
        raise ValueError(f"expected {len(posts)}, got {len(parsed)}")
    return parsed


def enrich_batch(posts, model):
    try:
        return call_claude(posts, model)
    except Exception as e:
        if len(posts) == 1:
            log(f"  enrich failed for {posts[0]['id']}: {e}")
            return [{"id": posts[0]["id"], "people_in_one_room": 1, "gender": None}]
        mid = len(posts) // 2
        return enrich_batch(posts[:mid], model) + enrich_batch(posts[mid:], model)


def main():
    cfg = load_config()
    settings = cfg.get("settings", {})
    model = str(settings.get("extract_model", "haiku"))
    batch_size = int(settings.get("extract_batch", 12))

    posts = {p["id"]: p for p in read_jsonl(POSTS_PATH)}
    # Only enrich actual seekers — no point profiling people offering rooms.
    seekers = [r["id"] for r in read_jsonl(EXTRACTED_PATH) if r.get("is_seeking")]
    done = {r["id"] for r in read_jsonl(ENRICHED_PATH)}
    todo = [posts[i] for i in seekers if i in posts and i not in done]

    log(f"{len(seekers)} seekers, {len(todo)} to enrich ({len(done)} already done)")
    for i in range(0, len(todo), batch_size):
        batch = todo[i:i + batch_size]
        append_jsonl(ENRICHED_PATH, enrich_batch(batch, model))
        log(f"  enriched {min(i + batch_size, len(todo))}/{len(todo)}")
    log(f"Enrichment complete -> {ENRICHED_PATH}")


if __name__ == "__main__":
    main()

"""Label a candidate's likely gender from their FIRST NAME.

This LABELS, it does not filter. A household can have a preference (see
preferences.prefer_gender in config.yaml) and knowing lets you sort by it, but
nobody is excluded or deleted by this pass. Therefore:
  - every candidate stays in candidates.csv and in Notion, whatever the label
  - ambiguous names come back "unisex"/"unknown" rather than a confident guess
  - a self-stated gender from enrich.py always wins over this name guess

Results are cached per lowercased first name in cache/gender.jsonl.
Usage: python -m pipeline.gender
"""
import json
import subprocess

from .common import CACHE_DIR, POSTS_PATH, log, read_jsonl, append_jsonl

GENDER_PATH = CACHE_DIR / "gender.jsonl"

PROMPT_HEADER = """\
You label first names by the gender most people with that name have.

For each name return an object with:
- "name": copied verbatim from the input
- "gender": "male" | "female" | "unisex" | "unknown"
    "male"/"female" ONLY when the name is strongly associated with one gender
      across the cultures it comes from (e.g. "Jessica" female, "Thomas" male).
    "unisex" when it is genuinely used for both (e.g. "Jordan", "Cam", "Alex").
    "unknown" for usernames, initials, business names, or names you cannot place
      (e.g. "FancyCrocodile6533", "J", "NYC Rentals").
- "confidence": "high" | "medium" | "low"

Be honest about uncertainty: prefer "unisex" or "unknown" with low confidence
over a confident guess. Non-Anglophone names count: judge them by their own
culture's usage, not by how they look in English.

Return ONLY a JSON array, one object per name, in the same order as the input.
No prose, no markdown fences.

NAMES:
"""


def first_name(full: str) -> str:
    return (full or "").strip().split()[0].lower() if (full or "").strip() else ""


def classify(names: list, model: str = "haiku") -> list:
    prompt = PROMPT_HEADER + json.dumps(names, ensure_ascii=False)
    result = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed: {result.stderr.strip()[:300]}")
    text = result.stdout
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON array in output: {text[:200]}")
    return json.loads(text[start:end + 1])


def load_cache() -> dict:
    return {r["name"]: r for r in read_jsonl(GENDER_PATH)}


def main() -> None:
    names = sorted({first_name(p.get("author_name")) for p in read_jsonl(POSTS_PATH)})
    names = [n for n in names if n]
    cached = load_cache()
    todo = [n for n in names if n not in cached]
    log(f"{len(names)} distinct first names, {len(todo)} to classify "
        f"({len(cached)} cached)")

    for i in range(0, len(todo), 60):
        batch = todo[i:i + 60]
        try:
            results = classify(batch)
        except Exception as e:
            log(f"  classify failed for batch at {i}: {e}")
            continue
        append_jsonl(GENDER_PATH, results)
        log(f"  classified {min(i + 60, len(todo))}/{len(todo)}")

    log(f"Name gender cache -> {GENDER_PATH}")


if __name__ == "__main__":
    main()

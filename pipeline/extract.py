"""LLM extraction: seeker intent + requested date range from each post.

Uses `claude -p` in headless mode. Results are cached per post id in
cache/extracted.jsonl so each post is only ever parsed once.
"""
import json
import re
import subprocess
from datetime import date, timedelta

from .common import POSTS_PATH, EXTRACTED_PATH, load_config, log, read_jsonl, append_jsonl

# Recall-oriented prefilter: a post with no date-ish token can't specify a timeframe.
# False positives only cost a model call; a false negative is a seeker lost for good.
DATE_HINT = re.compile(
    r"(jan|feb|apr|may\b|jun|jul|aug|sep\b|sept|september|oct|nov|dec|"
    r"labor\s*day|thanksgiving|christmas|xmas|holiday|winter|new\s*year|semester|"
    r"\b\d{1,2}\s*[/.-]\s*\d{1,2}\b|"
    r"week|month|asap|move.?in|mid|early|late|end of)",
    re.IGNORECASE,
)


def thanksgiving(year: int) -> date:
    """Fourth Thursday of November."""
    first = date(year, 11, 1)
    return first + timedelta(days=(3 - first.weekday()) % 7 + 21)


def year_rule(today: date) -> str:
    """Dates without a year mean the upcoming occurrence, so a request made in
    October for "Dec 20 - Jan 5" lands in Dec this year and Jan next year."""
    this_year = [date(2000, m, 1).strftime("%B") for m in range(max(today.month - 1, 1), 13)]
    next_year = [date(2000, m, 1).strftime("%B") for m in range(1, max(today.month - 1, 1))]
    rule = f"For dates without a year: {this_year[0]} through December are {today.year}"
    if next_year:
        rule += f"; {next_year[0]} through {next_year[-1]} are {today.year + 1}"
    return rule + (f'. A range that crosses New Year ("Dec 20 - Jan 5") ends in '
                   f"{today.year + 1}.")


def prompt_header(today: date) -> str:
    return f"""\
You extract structured data from Facebook group posts about NYC housing.
Today's date is {today.isoformat()}. {year_rule(today)}
Thanksgiving {today.year} is {thanksgiving(today.year).strftime('%B %-d')}.

For each post return an object with:
- "id": copied verbatim from the input
- "is_seeking": true ONLY if the author is LOOKING FOR a place to stay for
  themselves (or someone they represent). Posts OFFERING/listing a room,
  apartment, or sublet are false.
- "start_date": "YYYY-MM-DD" or null — start of the timeframe they need housing
- "end_date": "YYYY-MM-DD" or null
- "date_text": the verbatim phrase they used for dates, or null
- "budget": their stated budget as written (e.g. "$1500/mo"), or null
- "confidence": "high" | "medium" | "low" for the date interpretation
- "term": "long" if they want a lease of 6+ months, a yearly lease, or describe
  it as long-term/permanent; "short" if a sublet or stay under 6 months; else null

Interpret fuzzy phrases sensibly: "early <month>" ~ days 1-7, "mid-<month>" ~ the
15th, "late <month>" / "end of <month>" ~ 25th to month end, "the month of <month>"
= the whole month, "over the holidays" / "winter break" ~ Dec 15 - Jan 15
(confidence "medium"), "Thanksgiving to New Year's" = Thanksgiving through Jan 1.
If they give only a start ("from Dec 1"), leave end_date null. If no timeframe
at all, both null with confidence "low".

Return ONLY a JSON array with one object per post, in the same order as the
input. No prose, no markdown fences.

POSTS:
"""


def call_claude(posts: list, model: str) -> list:
    payload = [{"id": p["id"], "text": p["text"][:1500]} for p in posts]
    prompt = prompt_header(date.today()) + json.dumps(payload, ensure_ascii=False)
    result = subprocess.run(
        ["claude", "-p", "--model", model, "--output-format", "text"],
        input=prompt, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed: {result.stderr.strip()[:300]}")
    text = result.stdout
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"no JSON array in claude output: {text[:200]}")
    parsed = json.loads(text[start:end + 1])
    if len(parsed) != len(posts):
        raise ValueError(f"expected {len(posts)} objects, got {len(parsed)}")
    return parsed


def extract_batch(posts: list, model: str) -> list:
    """Parse a batch, bisecting on failure so one bad post can't sink the rest."""
    try:
        return call_claude(posts, model)
    except Exception as e:
        if len(posts) == 1:
            log(f"  extraction failed for {posts[0]['id']}: {e}")
            return [{"id": posts[0]["id"], "is_seeking": False, "error": str(e)[:200]}]
        mid = len(posts) // 2
        return extract_batch(posts[:mid], model) + extract_batch(posts[mid:], model)


def main() -> None:
    cfg = load_config()
    settings = cfg.get("settings", {})
    model = str(settings.get("extract_model", "haiku"))
    batch_size = int(settings.get("extract_batch", 12))

    posts = read_jsonl(POSTS_PATH)
    done = {r["id"] for r in read_jsonl(EXTRACTED_PATH)}
    todo = [p for p in posts if p["id"] not in done]

    skipped = [p for p in todo if not DATE_HINT.search(p["text"])]
    todo = [p for p in todo if DATE_HINT.search(p["text"])]
    if skipped:
        append_jsonl(EXTRACTED_PATH, [
            {"id": p["id"], "is_seeking": False, "skipped": "no date tokens"}
            for p in skipped
        ])

    log(f"{len(posts)} posts total, {len(todo)} to extract "
        f"({len(skipped)} skipped: no date language, {len(done)} cached)")

    for i in range(0, len(todo), batch_size):
        batch = todo[i:i + batch_size]
        results = extract_batch(batch, model)
        append_jsonl(EXTRACTED_PATH, results)
        log(f"  extracted {min(i + batch_size, len(todo))}/{len(todo)}")

    log(f"Extraction complete -> {EXTRACTED_PATH}")


if __name__ == "__main__":
    main()

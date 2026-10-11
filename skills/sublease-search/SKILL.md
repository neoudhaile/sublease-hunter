---
name: sublease-search
description: Use when the user says "search" on its own, or asks to run the sublease search. Runs the three sublease passes in order - conversations, posts, outreach.
---

# search

When the user types **"search"**, run three passes in this order and report what
happened in each. All commands run from the repo root.

```
.venv/bin/python -m pipeline.search all
```

That prints all three worklists in one go, read-only. Then act on them:

| # | Pass | Skill | What it does |
|---|---|---|---|
| 1 | conversations | `sublease-conversations` | Answer anyone who replied, then nudge people who went quiet a day or more ago |
| 2 | posts | `sublease-posting` | Post the listing in 2–3 groups that do not carry it yet |
| 3 | outreach | `sublease-outreach` | Message new tier A/B people nobody has contacted |

**The order is the point.** A lead who replied is worth more than a stranger, and
a listing sitting in a 195K-member group earns leads while you sleep. Do not
start pass 3 until 1 and 2 are done.

## Budget for one run

- Replies to `Replied` people: unlimited, they are existing threads.
- Nudges: at most 5.
- Posts: 2–3 groups.
- New message requests: up to Facebook's ~10 per 24h, counting cold DMs only.
  Stop at the limit notice and comment on posts instead.

Spend the DM budget on pass 3, not pass 1 — nudges are free, cold messages are
the scarce resource.

## Report back

One short section per pass: who was answered, who was nudged, where the listing
went, who was newly contacted. Name anything that needs the user: a specific
question from a lead, a group gated behind a questionnaire, a limit hit.

## Before finishing

Every action must be written to Notion — `notion_status` for people,
`notion_posts` for groups. The next run reads that board to decide what is left,
so an unrecorded send becomes tomorrow's double-text.

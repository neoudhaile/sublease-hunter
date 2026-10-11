---
name: sublease-posting
description: Use when posting the user's sublease listing to Facebook groups that do not carry it yet, or when checking which groups still need it. Also the second pass of "search".
---

# Sublease posting

Put the listing in groups that do not already have it this period.

## Get the worklist

```
.venv/bin/python -m pipeline.search posts
```

Read-only. It crosses the group registry against the Notion **Posts** board and
returns groups where we are a member, posting is possible, and no row says
`Live` or `Pending approval` for this period. Biggest membership first.

It also prints what is blocked or unjoined, so a group never silently
disappears from the plan.

## How many

**Two or three per run, a couple of hours apart.** Posting the same listing into
a dozen groups inside an hour is what draws a block. Posting is never
unattended.

Work down from the largest membership — a 195K group is worth more than five
small ones.

## Posting mechanics

Full procedure: `docs/posting-sop.md`. The parts that break if you improvise:

1. Open the composer and get the listing text in **first**, before photos —
   attaching photos first wipes the text every time.
   **Insert it with a synthetic paste event, not keystrokes.** Facebook's
   editor ignores synthetic keystrokes, so a `computer type` call silently does
   nothing; focus the `[role=textbox]`, build a `DataTransfer`, and dispatch
   `new ClipboardEvent('paste', {clipboardData, bubbles:true, cancelable:true})`.
   Read the box back before re-pasting, or you get two copies.
2. Surface the hidden file input with JS, upload the photos, then hide the input
   again before clicking back into the text field or it steals focus.
   **The photos must sit inside the session's working directory** — uploads from
   outside it are refused.
3. Guard the Post click: only click when the dialog actually contains the title
   and dates. This has already caught one would-be empty post.

Copy comes from `listing_post.txt`. **No price**, unless the group's registry
entry says `requires_price: true` — then add one line, `Price: $<rate> a night`,
after the Location line, using `listing.nightly_rate` from `config.yaml`.

## Before posting in a group

Check `facebook.com/groups/<id>/my_posted_content` and `my_pending_content`. A
current-period post is one containing this window's title or dates. A listing
from an earlier letting period does **not** block reposting.

## After each post

```
.venv/bin/python -m pipeline.notion_posts add \
    "<exact group name from the registry>" "<permalink>" "Live" "Posted <date>, N photos"
```

Use `Pending approval` when it goes to an admin queue, `Blocked` when a
questionnaire or membership gate stops you. The group name must match the
registry exactly or the next run will think the group is still unposted.

Then update the registry entry: set `post:` to what you observed (`ok`,
`admin-queue`, `blocked`) and bump `last_verified`.

## Common mistakes

| Mistake | Why it hurts |
|---|---|
| Photos before text | The text silently vanishes; you post pictures with no listing |
| Posting a price unprompted | Breaks the price rule; price belongs in DMs |
| Group name not matching the registry | The group looks unposted forever and gets a duplicate |
| Bullet lists | Facebook turns "- " into "• -" and mangles the post |
| Paying a group "access fee" | Never. Mark the group Blocked instead |

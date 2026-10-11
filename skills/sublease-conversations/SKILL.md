---
name: sublease-conversations
description: Use when working the sublease lead conversations - someone replied and needs an answer, or people were messaged days ago and went quiet and need a nudge. Also the first pass of "search".
---

# Sublease conversations

Work the people already in play before chasing new ones. A lead who replied is
worth more than ten strangers.

## Get the worklist

```
.venv/bin/python -m pipeline.search conversations --quiet-days 1
```

Read-only. It returns two lists off the Notion People board:

- **LIVE** — Status `Replied`. They wrote back and are waiting on us.
- **GONE QUIET** — Status `DM'd` or `Commented`, with a `Contacted` date at
  least `--quiet-days` old and no reply since.

## Order of work

1. **LIVE first, always.** Answer every one before sending a single nudge.
   Apply the reply playbook in `sublease-outreach-voice`: a price question or
   bare interest gets the nightly rate plus a call offer; anything specific goes
   to the user rather than being guessed at.
2. **Then nudges, best fit first.** The list is already sorted Tier A before B,
   then by nights covered.

## Nudge budget

Replies inside an existing thread do **not** count against Facebook's cap, so
answering LIVE people is always free. A nudge to someone who never replied is
also an existing thread, so it is free too — but it is still a message to a real
person. **Send at most 5 nudges per run** and stop if anyone's thread shows a
reply you missed.

Someone contacted today is not quiet. Default `--quiet-days 1` means "yesterday
or earlier"; raise it to 3 for a gentler cadence.

## Writing the nudge

One sentence, no new pitch, no price if they never got one. Reference the room
and leave the door open:

> still got the {area} room free {window} if you're looking

Never re-send the original message. Check the open thread before typing: if it
already shows your message twice, you have nudged them before.

## After each send

```
.venv/bin/python -m pipeline.notion_status "<post-url-fragment>" "Followed up"
```

That stamps `Contacted` with today, so the same person cannot surface as quiet
again tomorrow. Use `Replied` when they answer, `Ruled Out` when they decline.

## Common mistakes

| Mistake | Why it hurts |
|---|---|
| Nudging before answering a `Replied` lead | The warm one goes cold while you chase cold ones |
| Re-sending the original message | Reads as a bot; the duplicate is obvious in-thread |
| Forgetting to set `Followed up` | They resurface tomorrow and get nudged twice |
| Nudging a `Ruled Out` person | They already said no |

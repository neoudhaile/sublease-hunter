---
name: sublease-outreach
description: Use when finding new people to add to the sublease backlog and sending them a first message. Also the third pass of "search".
---

# Sublease outreach

Find people who have not been contacted, message the best of them, and leave
the board truthful.

## Get the worklist

```
.venv/bin/python -m pipeline.search outreach
```

Read-only. It reads `out/to_contact.csv` — tier A and B whose Notion Status is
still `New` — and splits it:

- **TO CONTACT** — message these.
- **HELD BACK** — only when `preferences.prefer_gender` is set in `config.yaml`:
  names that read confidently as the other gender. Shown, not messaged.

If the list is thin or stale, refresh it first:

```
./run.sh --days 3 --limit 80 --rotate 25
```

## On the held-back list

With `prefer_gender: none` (the default) nothing is held back and this section
does not apply.

When a preference is set, `unisex` and `unknown` names stay in the TO CONTACT
list **on purpose**. A name-based guess is wrong often enough that dropping
them would throw away real candidates; the user can eyeball a profile in
seconds, and a wrongly-dropped lead is gone for good.

Held-back people are **not deleted**. They stay on the board with their label,
because the room might not fill and the data cost real money to gather. If the
user wants them out of the working set, set their Status to `Ruled Out` — that
keeps the record and removes them from every worklist.

## How many

Facebook caps message requests to strangers at about **10 per 24 hours** and the
limit notice is unmissable: *"You've reached the message request limit."* Work
down the list until you hit it, then switch to commenting on the remaining
people's posts, which is not capped the same way.

Replies inside an existing thread do not count against the cap.

## Writing the first message

Load `sublease-outreach-voice`. The rules that matter most here:

- **No price in a cold message.** Dates, the room, an offer of pics. A number
  gives a stranger something to refuse before they have seen the place.
- Quote **their own dates** back in their words.
- Say plainly if their dates only partly overlap, rather than letting them find
  out later.
- Skip anyone who wants a 6+ month lease, a different unit type, or a different
  neighbourhood. The ranker scores on dates alone and does not know any of
  that — read the post.

## After each send

```
.venv/bin/python -m pipeline.notion_status "<post-url-fragment>" "DM'd"
```

Use `Commented` when you commented instead. This stamps `Contacted`, which is
what makes them eligible for a nudge later and keeps them out of
`to_contact.csv` tomorrow.

## Finding more people

When the list runs dry, the bottleneck is supply, not ranking:

- **New groups.** Search Facebook groups, add each to `groups/<city>.yaml` with
  a note on where it came from, join it, set `read: true`, then re-run the
  pipeline. Never scrape a group that is not in the registry.
- **Blocked groups.** Some need a membership questionnaire only the user can
  answer. Surface them rather than working around them.

## Common mistakes

| Mistake | Why it hurts |
|---|---|
| Messaging from `candidates.csv` | That file is everyone, contacted or not. Double-texts follow |
| Including the price | Cold messages carry no number |
| Trusting the tier blindly | Tier is dates only. Check unit type, area and budget in the post |
| Dropping unisex/unknown names | Throws away real candidates on a coin-flip guess |
| Forgetting to set Status | They resurface tomorrow and get messaged twice |

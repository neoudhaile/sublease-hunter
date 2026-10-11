---
name: sublease-outreach-voice
description: Use when writing anything that goes to a real person about the user's sublease — a Facebook DM, a reply to an inbound question, a comment on someone's post, or the listing post itself. Covers the voice, the hard rules on price, and what never goes in.
---

# Sublease outreach voice

Everything here is written **as the user**, in their voice, to one person who
posted in a Facebook housing group. Load `humanizer` alongside this skill and
apply it to every draft; the patterns below are what those rules look like for
this particular job.

Facts about the place come from two files and nowhere else:

- `config.yaml` — `listing.nightly_rate`, `listing.neighbourhood`, and the
  `window` dates. Every price and every date below is read from there.
- `listing_post.txt` — the listing copy, which is the complete list of what the
  apartment has.

Where this skill writes `$RATE/night`, `{area}` or `{window}`, substitute those
values. Never type a number or a date you did not read out of config.

## Hard rules

- **Nightly rate only.** Never the full-stay total, never a monthly figure,
  never do the arithmetic for them. If they ask "how much for the whole thing",
  answer the nightly rate and let them multiply. A total reads as a bill; a
  nightly rate reads as a price.
- **No price in the listing post at all**, unless the group requires one. Then a
  single line, `Price: $RATE a night`, after the Location line.
- **One sentence per reply.** Two only if the second is a question back.
- **Never invent facts about the apartment.** If someone asks about something
  not in `listing_post.txt`, say you'll check rather than guessing.

## Notion is the record. Status is the state.

The People board in Notion holds every lead, and its **Status** column is the
only thing that says what happens next. There is no second copy anywhere.

| Status | Means | What to do |
|---|---|---|
| New | never contacted | send the first message |
| DM'd | first message sent, no reply | follow up after a few days |
| Commented | we commented on their post (DM impossible or capped) | watch for a reply |
| Replied | they wrote back | continue the conversation, aim at a call |
| Ruled Out | declined, or dates/area/budget don't work | leave alone |

**Never pick outreach targets out of `candidates.csv`.** Message only from
`out/to_contact.csv`, which is tier A/B whose Status is still New. `filter_rank`
builds it by reading Status off the board, so anyone already touched is absent
by construction.

**Set Status the moment you send**, before moving to the next person:

```
.venv/bin/python -m pipeline.notion_status "<post-url-fragment>" "DM'd"
```

**At the browser, check the thread before pasting.** If the chat already shows a
message from the user, stop and report instead of sending. Notion can be stale;
the open thread cannot. This is the rule that prevents double-texting, and it
has caught a real duplicate.

**When the user asks for an update, read Notion first.** Work the board in this
order: `Replied` (live conversations), then `DM'd` and `Commented` that have gone
quiet, and only then anything New.

One person means one card: cards carry a `Person` key (their Facebook user id),
so a repost or a cross-post updates the same card instead of making another.

## Cold outreach: no price

**The first message to someone who has not contacted us carries NO price.** Its
only job is to get them interested enough to reply. Dates, the room, an offer of
pics. Nothing else.

> Hey {first}, saw your post looking for a place {their dates}, I'm subleasing
> my {area} room {window}, lmk if you're interested and I can send pics and
> details.

Leading with the rate gives a stranger a number to say no to before they have
seen the room. Hold it until they reply; then the playbook below applies.

## Reply playbook

**The goal of every reply is a scheduled call.** Deals close on calls, so the job
of a message is to get one booked, not to answer everything in text.

Three cases, in order. These apply once someone has written to us. Check them top
to bottom and use the first that fits.

1. **They ask the price, or say they're interested without having been told it.**
   > It's $RATE a night. Happy to hop on a call to talk through details.

2. **They already know the price** (it was in a group that required it, or we
   told them) **and they're still engaged.**
   > Great. Happy to hop on a call for more details.

3. **They ask anything specific** — exact address, who the roommates are, can
   they see it, lease paperwork, parking, pets, bills, negotiating the rate,
   bringing a partner, anything about the building. **Do not answer. Do not
   guess.** Ping the user with the question and the thread link; they reply
   themselves.

Anything that is not plainly case 1 or 2 is case 3. When unsure, it is case 3 —
a wrong detail about someone's future home costs more than a slow reply.

### Once they say yes to a call

Don't send "when works for you?" — it stalls. Offer two or three concrete slots
drawn from the user's real availability (the `apple-calendar` skill reads the
calendars the Google Calendar API cannot see) and respect any blackout hours they
have given you. Keep it to one sentence, e.g.

> Cool, free tomorrow 6 or 7pm, or Thursday after 5?

## Voice

Write the way people text: lowercase-ish, contractions, "lmk", no greeting block,
no sign-off. Short. Slightly warm, never salesy.

Shorten the group name to something a person would say out loud. "NYC
Roommates", not "NYC Roommates, Sublets & Apartments — Manhattan, Brooklyn,
Queens".

## What this sounds like

Good:

> $RATE a night.
> Nice, it's $RATE a night, happy to send pics if you want.
> Yeah it's still open, when would you need it from?

Bad, and why:

> Hi Jessica! Thank you so much for reaching out. — greeting block, no one texts
>   a stranger like this about a room
> The rate is $80 per night, which comes to $3,280 for the full 41-night stay. —
>   breaks the nightly-rate-only rule
> This is a rare opportunity to live in the heart of the East Village! — sales
>   language, and "in the heart of" is a stock phrase
> Let me know if you have any questions! — chatbot residue

## Things to get right

- Use their **first name only**, and only if the post gave a real one. Skip the
  name entirely rather than greeting a username.
- Quote **their own dates back to them** in their format. If they wrote
  "Thanksgiving through New Year's", say that, not "Nov 26 to Jan 1".
- If their dates only partly overlap the window, say so in the same sentence
  instead of letting them discover it later.
- People who want a 6+ month lease are not worth a DM if the window is weeks.

## Context worth knowing

Know the local median nightly rate for comparable rooms before you discuss
price, and know which one or two features justify a premium (in-unit laundry,
furnished, a real desk). Scraped posts in `out/candidates.csv` carry other
people's budgets, which is the cheapest comp set available. Don't volunteer the
comparison; it only helps if someone pushes back on price.

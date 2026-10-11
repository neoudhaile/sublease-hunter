---
name: sublease-setup
description: Use when someone has just cloned sublease-hunter, says "setup" or "set up", asks how to start, or when a command fails because config.yaml, a Notion board, a token or the Facebook session is missing. Walks them through connecting everything and writing their listing.
---

# Sublease setup

Walk one person from a fresh clone to a working pipeline. **Talk them through it,
one step at a time** — do not dump the whole checklist and wait. Do every step
you can do yourself; ask only for what lives in their head or behind their
password.

They are subletting their own place and have probably never seen this repo.
Assume nothing about their dates, their rate, or their city.

## Step 0: find out where they are

```
.venv/bin/python -m pipeline.doctor
```

That is the whole state of the install in one screen: Python, dependencies, the
`claude` CLI, `config.yaml`, the Notion token and each page, the group registry,
the Facebook session, the listing copy and photos. It is read-only and free —
**run it before asking a single question**, and again after each step that
should have fixed something.

Blockers are `FAIL`. Warnings cost features, not correctness. Work the list top
to bottom; each line carries its own fix.

If the install itself is missing:

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

## Step 1: check your own tools, not just theirs

The doctor cannot see what *you* have. Check and report these yourself, because
each one silently removes a feature:

| Tool | Needed for | Without it |
|---|---|---|
| A browser tool (Claude in Chrome, or the in-app browser) | posting, DMs, replies | Scraping and ranking still work; every message is manual |
| Notion (MCP connector) | reading the boards conversationally | The pipeline still writes via the API; you just can't browse it in chat |
| A calendar tool (`apple-calendar` skill, or a calendar MCP) | offering real slots when a lead says yes to a call | You have to ask them for times instead of offering them |

Say plainly which of the three you have. If the browser is missing, say so
before they rely on this for outreach — that is the half of the job a human
would otherwise do by hand.

## Step 2: the five questions

Ask these **in this order**, conversationally, one or two at a time. Write each
answer straight into `config.yaml` as you get it, so an interrupted setup
resumes where it stopped.

1. **When is your place free?** → `window.start` / `window.end`. Everything is
   ranked by how many of these nights a person covers, so get the real
   checkout and return dates, not approximate ones. Convert "Thanksgiving to
   New Year" to ISO dates and read them back for confirmation.
2. **Where is it?** → `listing.neighbourhood`. A neighbourhood, not a street
   address — this goes in messages to strangers. Also ask which **city**, so the
   group registry matches: `groups/nyc.example.yaml` is NYC. For anywhere else,
   copy it and swap the groups.
3. **What are you charging a night?** → `listing.nightly_rate`. Nightly, not
   monthly, even if they think in rent. If they do not know, ask what similar
   rooms go for locally; after the first scrape, other people's budgets in
   `out/candidates.csv` are a real comp set.
4. **A whole place or a room in a share?** → `listing.unit_type`. If it is a
   room, ask whether a couple sharing it is acceptable. Default is one person.
5. **Do you have photos?** Get them into `listing_photos/` (6–8 is right; a post
   with photos gets far more replies). They must sit inside the project
   directory or uploads are refused.

Only ask about `preferences.prefer_gender` if they bring up who they want in the
room. It defaults to `none`, which labels gender and changes nothing. If they
do state a preference, tell them what it actually does: a match ranks one notch
up, the opposite one notch down and is held out of the automatic outreach list
for them to decide on by hand. Nobody is deleted, and ambiguous names are never
held back.

## Step 3: Notion

They need a Notion account and an internal integration. Guide them:

1. https://www.notion.so/my-integrations → new internal integration → copy the
   token → paste into `.env` as `NOTION_TOKEN=`.
2. In Notion, a page for this sublet, with two sub-pages: **People** and
   **Posts**.
3. On each of the three pages: `•••` → Connections → add the integration. This
   is the step everyone forgets, and the symptom is a 404 the doctor explains.
4. The page id is the 32-hex string in the page URL → `config.yaml`.

Re-run the doctor. It names which page is not shared.

The databases themselves are created by the first `./run.sh`, under those pages.

## Step 4: Facebook

```
.venv/bin/python fb_login.py
```

A window opens; **they** type their credentials. **Never type a password, a PIN
or a 2FA code for them**, even if they offer it in chat — hand the keyboard
back. The session saves itself and the window closes.

Then the groups: nothing is scraped or posted outside `groups/<city>.yaml`. For
each group they are already in, set `membership: member`, `read: true`, and
`post: untested`. They have to join the rest themselves — joining is a human
act and some groups ask questionnaires. The shipped NYC file is a starting
point with all membership state reset, not a claim about their account.

## Step 5: the listing

Offer both routes, in this order:

- **"I'll draft it from your photos."** Look at the images, then write
  `listing_post.txt` in the house style: a title line, a Dates line, a Location
  line (cross streets, never the exact address), then two or three sentences on
  the room. **Sentences, never bullet points** — Facebook turns "- " into "• -".
  Mention a deposit only if they said there is one. **No price in the post**
  unless a group demands one. Show them the draft and let them cut anything.
- **"Or paste your own."** If they already have copy that works, use it
  verbatim. Do not rewrite it to taste.

Either way, read it back and confirm before it goes anywhere. It is their home
and their name on it.

## Step 6: prove it works offline

```
./run.sh --fixtures
```

Ten sample posts through the real pipeline — extraction, ranking, CSVs — without
touching Facebook. Show them `out/candidates.csv`: the tiers, and why each
person got theirs. This is the moment the ranking stops being abstract.

Then the real thing:

```
./run.sh --days 3 --limit 40
```

## Step 7: explain what they just built

Keep it to a few sentences, in their words, not the repo's:

- **Every day it reads the groups you listed** and ranks everyone looking for a
  place by how many of your nights they could actually take. It does not message
  anyone.
- **Notion is the only record.** The Status column on each card says what happens
  next: New → DM'd → Replied → Ruled Out. Set it the moment something happens, or
  the next run will think nothing did.
- **You say "search"** and three things happen in order: everyone who replied
  gets answered, the listing goes into two or three groups that do not have it,
  and new good-fit people get a first message. Dates and the room, never a price,
  in that first message.
- **Facebook caps cold messages at about 10 a day.** That is the real limit on
  how fast this goes, and it is why the ranking matters.
- **Posting and messaging are never unattended.** You will see each one.

## Step 8: hand over

End with one concrete next action, not a menu:

> Everything's connected. Say **search** and I'll start with the groups you're
> already in.

If anything is still a warning — no photos, no listing copy, three groups
joined — say what it costs them and let them decide whether to fix it now.

## Common mistakes

| Mistake | Why it hurts |
|---|---|
| Dumping the whole checklist at once | They close the terminal. One step at a time |
| Asking questions the doctor already answered | Run it first; it knows what is missing |
| Writing a listing before seeing the photos | You invent features. Ask, or look |
| Typing their password or PIN "to save time" | Never. Hand the keyboard back |
| Saying "set up Notion" and moving on | The sharing step is the one that fails. Walk it |
| Setting `read: true` on groups they have not joined | Scrapes come back empty and look broken |
| Skipping `--fixtures` | They first see the pipeline on live data, where a bug costs real leads |

# sublease-hunter

Find someone to take your room while you're away.

You post a sublet in a few Facebook housing groups, a dozen people reply, and
within a week you have no idea who you've already answered. This repo does the
bookkeeping: it scrapes the groups you're in for people *looking* for a place,
ranks them by how much of your empty window they'd actually cover, keeps every
lead on a Notion board whose Status column says what happens next, and gives an
AI agent a set of skills for working that board without double-texting anyone.

**Scraping and ranking are automated. Messaging and posting are not** — those
need a logged-in browser and a human who looked at the screen. The daily job
only ever reads.

```
groups/<city>.yaml ──► scrape ──► extract ──► rank ──► Notion "People"
   (what to read)       forage     claude     dates     (the only datastore)
                                                │
                              out/to_contact.csv ┘  ──► you, in a browser
```

## What it actually does

- **Scrapes** the groups you list, through a real logged-in browser session
  (ForageFacebook) or Apify if you'd rather pay for it.
- **Extracts** structured fields from free-text posts with Claude Haiku — the
  dates they want, their budget, whether it's a couple, whether they want a
  year's lease.
- **Ranks** every seeker by how many nights of *your* window they cover. Someone
  who needs a place two weeks before your room frees up is a long shot, however
  good the overlap looks; someone who wants a 12-month lease is not taking a
  six-week sublet. Those rules are in the tiering, not in your head.
- **Dedupes on the Facebook user id**, so the same person reposting in four
  groups is one card, not four.
- **Tracks posts** too: which groups carry your listing, which are pending admin
  approval, which blocked you and why.
- **Ships agent skills** (`skills/`) that encode the parts that are easy to get
  wrong: don't answer a question about the apartment you can't verify, don't put
  a price in a cold message, check the open thread before pasting.

## Requirements

For the pipeline (scraping, ranking, Notion sync):

- Python 3.12+
- A Notion account (free is fine) and an [internal integration](https://www.notion.so/my-integrations)
- The [Claude Code](https://claude.com/claude-code) CLI on your PATH — the
  extraction step calls `claude -p`
- A Facebook account that is already a member of the groups you want to read

For the half an agent does — posting, DMs, booking calls — connect these to
Claude. Each one you skip still leaves a working pipeline; it just hands that
part back to you:

| Connect | For | Without it |
|---|---|---|
| A browser tool — Claude in Chrome, or Claude Code's in-app browser | posting the listing, sending DMs, reading replies | Scraping and ranking still work; every message is yours to send |
| **Notion** (MCP connector) | reading and editing the boards in conversation | The pipeline still reads and writes via the API; you just can't browse it in chat |
| A calendar — the `apple-calendar` skill, or a calendar MCP | offering real free slots when a lead agrees to a call | You pick the times by hand |

`python -m pipeline.doctor` checks everything on the first list. The agent
reports the second, since it can only see its own tools.

## Setup

### The short way: let the agent do it

Open the repo in Claude Code and say **`setup`**. It runs the connection check,
asks the handful of things only you know — when your place is free, where it is,
what you're charging, whether it's a room or the whole place — writes them into
`config.yaml`, walks you through Notion and the Facebook login, offers to draft
your listing from your photos (or takes copy you already have), proves the
pipeline works on sample data, and then explains what it will do before anything
goes near a real group. That walkthrough is `skills/sublease-setup/`.

At any point:

```bash
.venv/bin/python -m pipeline.doctor
```

prints the state of every connection — Python, dependencies, the `claude` CLI,
your config and window, the Notion token and each page, the group registry, the
Facebook session, your listing and photos — with the fix for each thing that is
missing. Read-only, no model call, nothing billable.

```
[  ok  ] window — 2027-03-01 to 2027-04-15 (45 nights)
[  ok  ] NOTION_TOKEN — authenticated as Sublease Automation
[ FAIL ] notion.people_page_id — Notion says 404 for People board page
         fix: open the page in Notion, ••• -> Connections -> add your integration
[ warn ] listing photos — 0 image(s) in listing_photos/
```

### The manual way

**1. Install**

```bash
git clone <your-fork> sublease-hunter && cd sublease-hunter
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
```

**2. Log into Facebook once**

```bash
.venv/bin/python fb_login.py
```

A browser window opens. You type your own credentials — nothing in this repo
sees or stores your password. The moment Facebook sets its logged-in cookie the
session is saved and the window closes by itself. Re-run it when the session
expires (the daily job tells you when that happens).

**3. Create the Notion boards**

In Notion: make a page for this sublet, then two sub-pages under it, **People**
and **Posts**. Create an [internal integration](https://www.notion.so/my-integrations),
copy its token, and share all three pages with it (`•••` → Connections).

The page id is the 32-hex string in the page URL.

**4. Configure**

```bash
cp .env.example .env                      # NOTION_TOKEN, optional APIFY_TOKEN
cp config.example.yaml config.yaml        # your window, your page ids, your rate
cp groups/nyc.example.yaml groups/nyc.yaml
```

Then edit `config.yaml`: the dates your place is free, the three Notion page
ids, your nightly rate and neighbourhood. Everything downstream is ranked
against that window.

**5. Pick your groups**

`groups/nyc.example.yaml` ships 32 real NYC housing groups as a starting point,
with all membership state reset — joining is yours to do. For each group you're
actually in, set `membership: member`, `read: true`, and `post:` to what you've
observed. The file header documents every field. For another city, start a new
registry and point `groups_registry` at it.

**6. Write your listing**

`listing_post.txt` is the copy that goes in groups (sentences, no bullet lists —
Facebook mangles them). `listing_photos/` is where its photos go. Both are
gitignored; they're yours.

**7. Try it offline first**

```bash
./run.sh --fixtures
```

That ingests `fixtures/posts.json` instead of scraping, so you can see the whole
pipeline work — extraction, ranking, CSVs — before pointing it at Facebook.

## Running it

```bash
./run.sh                           # full sweep: scrape → extract → rank → Notion
./run.sh --days 3 --limit 80       # a light pass over recent posts only
./run.sh --group "NYC Roommates"   # one group
./reset.sh                         # clear cache/, out/, raw/ for a clean run
```

Outputs land in `out/`:

| File | What it is |
|---|---|
| `candidates.csv` | everyone found, ranked, contacted or not |
| `new_candidates.csv` | just what appeared this run |
| `to_contact.csv` | **the list to message from** — tier A/B whose Status is still New |
| `coverage_report.md` | which groups produced anything |

### Daily, in the background

`daily_run.sh` is the unattended job: one sweep a day, push new cards to Notion,
a desktop notification only when a tier A or B lead appears. It stops by itself
once your window starts. On macOS:

```bash
cp com.example.sublease-hunter.plist ~/Library/LaunchAgents/   # edit the paths first
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.sublease-hunter.plist
```

Once a day is deliberate. An earlier schedule ran every two hours and turned up
the same feeds over and over: four runs in a day produced 55 new rows and not
one above tier C.

### Working the board: "search"

The agent-facing half of this repo. With Claude Code in the project, typing
**`search`** runs three passes in order:

1. **conversations** — answer everyone who replied, then nudge the people who
   went quiet. A lead who wrote back is worth more than ten strangers.
2. **posts** — put the listing in 2–3 groups that don't carry it yet.
3. **outreach** — first message to new tier A/B people nobody has contacted.

```bash
.venv/bin/python -m pipeline.search all     # prints all three worklists, read-only
```

`pipeline.search` only ever *decides*. Sending happens in a browser, with you
watching, and the result is written back with:

```bash
.venv/bin/python -m pipeline.notion_status "<post-url-fragment>" "DM'd"
.venv/bin/python -m pipeline.notion_posts add "<group>" "<permalink>" "Live" "<notes>"
```

The skills in `skills/` are the operating instructions for all of this —
`sublease-setup` (the first-run walkthrough), `sublease-search`,
`sublease-conversations`, `sublease-posting`, `sublease-outreach`, and
`sublease-outreach-voice` (the voice and the price rules). `.claude/skills`
symlinks to them so Claude Code picks them up automatically. `CLAUDE.md` holds
the standing rules.

## Notion is the datastore

There is no local database. Every lead is a card on the People board, and its
**Status** column is the state machine:

| Status | Means | Next |
|---|---|---|
| New | never contacted | send the first message |
| DM'd | sent, no reply | nudge after a few days |
| Commented | commented on their post (DM capped or impossible) | watch for a reply |
| Replied | they wrote back | keep talking, aim at a call |
| Ruled Out | declined, or dates/area/budget don't work | leave alone |

`filter_rank` reads Status back off the board when it builds `to_contact.csv`,
so anyone you've already touched drops out by construction. That one loop is
what stops the double-texting, and it only works if you set the Status the
moment you send.

`notion_state.json` records the database ids for the current letting period, so
last year's board is never written to by accident.

## Rate limits, and other things that will bite you

These are not suggestions; each one came from hitting it.

- **Facebook caps message requests to non-friends at about 10 per 24 hours.**
  At the cap, sends silently fail. Stop at the limit notice and comment on
  people's posts instead — a separate channel, not capped the same way. Replies
  inside an existing thread never count.
- **Post 2–3 groups per batch, hours apart.** The same listing in a dozen groups
  inside an hour is what draws a block.
- **Text before photos** in the composer, always. Attaching photos first wipes
  the text.
- **Facebook's editor ignores synthetic keystrokes.** Automated typing reports
  success and leaves the box empty; you have to dispatch a real paste event. Full
  procedure in `docs/posting-sop.md`.
- Never pay a group "access fee", never solve a CAPTCHA, never let an agent
  enter a password or a PIN. Mark the group blocked and move on.

## When something stops working

Run the doctor first; it checks the things that actually break.

The usual culprit is the **Facebook session expiring** every few weeks. The
symptom is not an error — it is a scrape that returns nothing. Re-run
`.venv/bin/python fb_login.py`.

If a Notion write 404s, the page is not shared with your integration
(`•••` → Connections). If extraction fails, `claude` is not on the PATH of
whatever launched the job — launchd does not inherit your shell's PATH.

## Privacy

This repo scrapes posts by real people looking for housing. `out/`, `cache/`,
`raw/` and `logs/` hold their names, profile links and post text, and
`.gitignore` keeps all of it — plus `.env`, `config.yaml`, your listing copy and
your photos — out of git. Don't override that. Keep the data as long as you're
looking and delete it when you're done.

## Layout

```
pipeline/           scrape → extract → enrich → gender → rank → notion sync
pipeline/doctor.py  is everything connected? (free, read-only)
skills/             agent operating instructions (symlinked into .claude/skills)
groups/             the group registry: what to read, where to post
docs/posting-sop.md the full posting procedure
fixtures/           sample posts, for running the pipeline offline
run.sh              the whole pipeline
daily_run.sh        the unattended daily sweep
fb_login.py         one-time login, saves its own session
reset.sh            clear scraped data
```

## License

MIT

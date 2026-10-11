# sublease-hunter: notes for agents

You are helping one person sublet their place. Their specifics — dates, rate,
neighbourhood — live in `config.yaml` and `listing_post.txt`. Read them; never
assume them.

## Facebook groups: work only within the registry

`groups/<city>.yaml` is the master list of Facebook groups we read from (scrape
for people seeking a sublet) and post in (list the user's room).

- Only read from or post in groups listed there. To use a new group, add an
  entry first, with a note on where you found it.
- Never delete entries. Mark dead ones `status: retired` with the reason.
- Whenever you observe a change (membership approved, post rejected, admin queue
  cleared, a group demanding a price), update the entry and its `last_verified`.
- The rules for each field are in that file's header.

## First contact: "setup"

If `config.yaml` is missing, or the user says **setup**, or asks how to start,
load the `sublease-setup` skill and walk them through it conversationally — one
step at a time, not as a checklist. `python -m pipeline.doctor` prints the state
of every connection (free, read-only, no model call); run it before asking any
question, and after any step that should have fixed something.

Report which of these *you* have, since the doctor cannot see them: a browser
tool (posting and DMs), Notion (reading the boards in chat), a calendar tool
(offering real slots for calls). Say what is missing before the user relies on
it.

## "search"

When the user types **search** on its own, that is a command: run the three
passes in `skills/sublease-search/` — conversations, then posts, then outreach,
in that order. `.venv/bin/python -m pipeline.search all` prints all three
worklists read-only.

## Listing rules

Before writing any message, comment or listing copy, load the
`sublease-outreach-voice` skill in `skills/` — it holds the voice, the price
rules and worked examples. Load `humanizer` with it.

- **No price in the listing**, unless the group requires one
  (`requires_price: true`, group rules, or an admin rejection that asks for it).
  Then use `listing.nightly_rate` from `config.yaml`. Price is otherwise
  discussed in DMs only.
- **Quote the nightly rate only, never a full-stay total or a monthly figure.**
- Write in sentences. No bullet lists, because Facebook turns "- " into "• -".
- **Notion is the single record for leads and posts; its Status column is the
  state machine** (New → DM'd/Commented → Replied → Ruled Out). No local ledger
  and no occupancy column: the room takes one person.
- **Never message from `candidates.csv`.** Outreach comes from
  `out/to_contact.csv`, which is tier A/B whose Status is still New. Set Status
  with `python -m pipeline.notion_status` the moment you send, and check the open
  thread before pasting.
- Facebook caps message requests to non-friends at about 10 per 24h. Hard stop
  at the limit notice, then comment on the person's post instead.
- The full posting procedure is in `docs/posting-sop.md`.

## Things never to do

These are refusals, not preferences. Hitting one of them means stopping and
telling the user, not finding a way around it.

- **Never enter a password, a PIN or a payment detail**, even if the user puts it
  in chat. Hand the keyboard back and let them type it.
- **Never pay a group "access fee"** or sign up for a third-party service a group
  demands. Mark the group `Blocked` and let the user decide.
- **Never solve a CAPTCHA** or any other bot check.
- **Never create an account** anywhere on the user's behalf.
- **Never commit scraped data**, `.env`, `config.yaml`, `listing_post.txt` or
  listing photos. `out/`, `cache/`, `raw/` and `logs/` hold real people's names
  and profile links; `.gitignore` covers them, so do not override it.
- Posting and DMing are human-approved, never unattended. The scheduled run only
  scrapes and ranks.

## Where state lives

- `config.yaml` — window, Notion ids, settings, your rate and area.
- `notion_state.json` — the database ids for the current letting period. One per
  period, so an old board is never written to.
- `listing_post.txt` — the listing copy. `listing_photos/` — its photos.
- Notion holds everything about people and posts: one **People** database
  (seekers we find) and one **Posts** database (where the room is listed).

## Development

`./run.sh --fixtures` is the offline smoke test: it ingests `fixtures/posts.json`
instead of scraping, so the whole pipeline can be exercised without touching
Facebook. It still calls the model for extraction.

`./reset.sh` clears `cache/`, `out/` and `raw/` for a clean run. It leaves your
login session alone.

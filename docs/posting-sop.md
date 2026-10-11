# Listing-post SOP

How to put your listing in a Facebook group without getting the post eaten or
the account flagged. Everything here was learned by doing it wrong first.

## HARD LIMIT: Facebook message requests

DMs to people you are not friends with are "message requests", and Facebook caps
them at roughly **10 per 24 hours**. At the cap you get *"You've reached the
message request limit"* and further sends do not deliver — silently, as far as
the recipient is concerned.

Rules:

- Space them out. Never batch ten at once.
- The moment the limit notice appears, **stop**. Do not try other recipients;
  the cap is per account, not per thread.
- Commenting on the person's post is a separate channel and is not capped the
  same way. When DMs are blocked, comment instead.
- Replies inside an existing thread do not count against the cap.

Posting cadence: **2–3 posts per batch, a couple of hours apart.** Posting the
same listing into a dozen groups inside an hour is what draws a block.

## Copy and photos

- Copy lives in `listing_post.txt`. Sentence format, **no bullet lists** —
  Facebook turns `- ` into `• -` and mangles the post.
- Photos: 8 compressed images, a few MB total, kept **inside the session's
  working directory**. Uploads from outside it are refused.

## Price rule

**No price in the listing**, except in groups that require one — the registry
entry says `requires_price: true`, the group rules demand it, or an admin
rejected the post asking for it. For those, add one line right after the
Location line:

```
Price: $<listing.nightly_rate from config.yaml> a night
```

When you learn a group requires a price, set `requires_price: true` on its
registry entry so the next run knows.

## Which groups

Post and read **only** in groups listed in `groups/<city>.yaml`. Add a new group
there, with a note on where you found it, before using it.

Before posting in a group, check:

- `facebook.com/groups/<id>/my_posted_content` (published)
- `facebook.com/groups/<id>/my_pending_content` (pending admin approval)

A group counts as already posted only if it carries a **current-period** post —
one with this window's title or dates. A listing from an earlier letting period
does not block reposting.

If a current-period post exists, skip posting and record its permalink to the
Notion Posts board (`Live`, or `Pending approval` if still in the queue).

## Posting flow, per group

1. Navigate to the group and open the composer. **Verify the Create Post modal
   is actually open** before typing — the inline box sometimes needs a second
   click, and typing into the page instead of the modal loses the text.
2. **Text first, photos second.** Attaching photos first wipes the text.
3. Insert the text with a **synthetic paste event**, not keystrokes. Facebook's
   editor ignores synthetic keystrokes, so a type call appears to work and
   leaves the box empty:

   ```js
   const box = document.querySelector('div[role="textbox"]');
   box.focus();
   const dt = new DataTransfer();
   dt.setData('text/plain', copy);
   box.dispatchEvent(new ClipboardEvent('paste',
       {clipboardData: dt, bubbles: true, cancelable: true}));
   ```

   **Read the box back before re-pasting.** A paste that reports empty may have
   landed; retrying appends a second copy.
4. Surface the hidden file input with JS, upload the photos, then hide the input
   again before clicking back into the text field or it steals focus.
5. Verify text **and** photos are present in the dialog, then click Post. Guard
   that click: only click when the dialog actually contains the title and dates.
6. Capture the permalink and write it to Notion:

   ```
   .venv/bin/python -m pipeline.notion_posts add "<group>" "<permalink>" "Live" "<notes>"
   ```

If a participation questionnaire or membership gate blocks posting, mark the
group `Blocked` with the reason. **Never pay a group "access fee"**, never solve
a CAPTCHA, and stop at any checkpoint rather than working around it.

## Every run, also

1. Capture the permalink of every current-period post you find in any group, so
   the user can verify each one.
2. Status-sweep blocked and pending groups: membership approvals landing,
   pending posts going published. Update Notion and the registry.
3. Report any group newly joined from the join queue — post there next batch.

Posting is human-approved, never unattended.

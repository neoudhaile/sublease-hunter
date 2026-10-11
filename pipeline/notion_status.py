"""Set the Status of a candidate's Notion card.

Usage: python -m pipeline.notion_status <post-url-or-id-fragment> <status>
Status: New | DM'd | Commented | Followed up | Replied | Ruled Out

Setting an outreach status also stamps the Contacted date, which is what
`pipeline.search conversations` uses to decide who has gone quiet long enough
to deserve a nudge.
"""
import os
import sys
from datetime import date

from .common import log
from . import notion_push
from .notion_push import api, load_state


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    fragment, status = sys.argv[1], sys.argv[2]

    from .common import load_config
    notion_push.configure(load_config())
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        log("NOTION_TOKEN not set")
        sys.exit(1)

    state = load_state()
    if not state.get("database_id"):
        log("No Notion database yet (run notion_push first)")
        sys.exit(1)

    result = api(token, "POST", f"/databases/{state['database_id']}/query", {
        "filter": {"property": "Key", "rich_text": {"contains": fragment}},
    })
    pages = result.get("results", [])
    if not pages:
        log(f"No card found with Key containing '{fragment}'")
        sys.exit(1)
    if len(pages) > 1:
        log(f"WARNING: {len(pages)} cards match; updating all")

    # Outreach statuses carry a date, so `pipeline.search conversations` can
    # tell who has gone quiet long enough to be worth a nudge.
    props = {"Status": {"select": {"name": status}}}
    if status in ("DM'd", "Commented", "Followed up"):
        props["Contacted"] = {"date": {"start": date.today().isoformat()}}

    for page in pages:
        name = "".join(
            t.get("plain_text", "")
            for t in page["properties"].get("Name", {}).get("title", [])
        )
        api(token, "PATCH", f"/pages/{page['id']}", {
            "properties": {"Status": {"select": {"name": status}}},
        })
        log(f"{name}: Status -> {status}")


if __name__ == "__main__":
    main()

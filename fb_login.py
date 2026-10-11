"""Facebook login for the scraper that saves itself, no Enter keypress needed.

Opens a browser at facebook.com/login. You type your own credentials (nothing
here sees or stores your password). The moment Facebook sets its logged-in
cookie, the session is written to forage's session file and the window closes.

Usage: .venv/bin/python fb_login.py
"""
import sys
import time

from forage.auth import get_session_path
from playwright.sync_api import sync_playwright

TIMEOUT_S = 15 * 60


def logged_in(context) -> bool:
    return any(c["name"] == "c_user" for c in context.cookies("https://www.facebook.com"))


def main() -> None:
    session_path = get_session_path()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.facebook.com/login")
        print("Log into Facebook in the browser window. It saves and closes by itself.",
              flush=True)
        deadline = time.time() + TIMEOUT_S
        while time.time() < deadline:
            if logged_in(context):
                time.sleep(4)  # let the remaining session cookies land
                context.storage_state(path=str(session_path))
                print(f"Session saved to {session_path}", flush=True)
                browser.close()
                return
            page.wait_for_timeout(2000)
        print("Timed out waiting for login.", flush=True)
        browser.close()
        sys.exit(3)


if __name__ == "__main__":
    main()

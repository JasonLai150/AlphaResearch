#!/usr/bin/env python3
"""One-time: create a Browserbase Context and log into wandb inside it.

Run this ONCE from your laptop. It opens a remote Browserbase browser, gives you
a live-view URL to click, you log into wandb by hand (handles SSO/MFA), and on
exit the Context saves your wandb cookies. Sub-agents later reuse the Context ID
(read-only, persist:false) so they can screenshot live wandb run pages without
ever holding credentials.

Usage:
    set -a; source .env; set +a
    python3 scripts/setup_browserbase_context.py            # set up (interactive login)
    python3 scripts/setup_browserbase_context.py --verify   # check the saved context (no login)

Output: prints BROWSERBASE_CONTEXT_ID and appends it to .env (gitignored).

Robustness: the CDP control socket is idle while you log in and Browserbase/your
network may drop it ("Debugging connection was closed"). We therefore reconnect
to the still-live session before reading cookies instead of crashing, and persist
relies on Browserbase's persist:true (it writes on session end regardless).

Deps (laptop only; NOT baked into the sub-agent image):
    uv pip install --python .venv/bin/python browserbase playwright
    .venv/bin/playwright install chromium   # only needed if you ever run local
"""
from __future__ import annotations

import os
import sys
import time

from browserbase import Browserbase
from playwright.sync_api import sync_playwright

WANDB_LOGIN = "https://wandb.ai/login?signup=false"
WANDB_HOME = "https://wandb.ai/home"


def _live_view_url(bb: Browserbase, session_id: str) -> str | None:
    """Best-effort fetch of the interactive live-view URL across SDK versions."""
    try:
        dbg = bb.sessions.debug(session_id)
    except Exception as e:  # noqa: BLE001
        print(f"  (couldn't fetch live-view URL: {e})")
        return None
    for attr in ("debugger_fullscreen_url", "debuggerFullscreenUrl",
                 "debugger_url", "debuggerUrl"):
        url = getattr(dbg, attr, None)
        if url:
            return url
    return None


def _wandb_cookies(browser) -> list[dict]:
    cookies = browser.contexts[0].cookies()
    return [c for c in cookies if "wandb" in (c.get("domain") or "")]


def _persist_ctx_id(ctx_id: str) -> None:
    """Save the context id to .env immediately so a later crash can't lose it."""
    try:
        existing = ""
        if os.path.exists(".env"):
            with open(".env") as f:
                existing = f.read()
        if "BROWSERBASE_CONTEXT_ID=" not in existing:
            with open(".env", "a") as f:
                f.write(f"\nBROWSERBASE_CONTEXT_ID={ctx_id}\n")
            print("  (appended BROWSERBASE_CONTEXT_ID to .env)")
    except OSError:
        pass


def _connect(p, connect_url):
    return p.chromium.connect_over_cdp(connect_url)


def verify(bb: Browserbase) -> int:
    ctx_id = os.environ.get("BROWSERBASE_CONTEXT_ID")
    if not ctx_id:
        print("ERROR: no BROWSERBASE_CONTEXT_ID (set it in .env or run setup first).")
        return 1
    print(f"==> verifying context {ctx_id} (read-only session, persist:false)")
    session = bb.sessions.create(
        browser_settings={"context": {"id": ctx_id, "persist": False}},
    )
    with sync_playwright() as p:
        browser = _connect(p, session.connect_url)
        wandb_cookies = _wandb_cookies(browser)
        names = sorted({c["name"] for c in wandb_cookies})
        # Active check: a logged-in session won't bounce /home to /login.
        landed = ""
        try:
            page = browser.contexts[0].pages[0] if browser.contexts[0].pages \
                else browser.contexts[0].new_page()
            page.goto(WANDB_HOME, wait_until="domcontentloaded", timeout=30000)
            landed = page.url
        except Exception as e:  # noqa: BLE001
            landed = f"(nav failed: {e})"
        browser.close()
    print(f"\n==> {len(wandb_cookies)} wandb cookie(s) in context: {names or 'NONE'}")
    print(f"==> /home landed on: {landed}")
    ok = bool(wandb_cookies) and "/login" not in landed
    print("\n" + ("✅ CONTEXT IS LOGGED IN — reuse this BROWSERBASE_CONTEXT_ID."
                  if ok else
                  "❌ NOT logged in — re-run setup (without --verify) and log in fully."))
    return 0 if ok else 2


def setup(bb: Browserbase) -> int:
    ctx_id = os.environ.get("BROWSERBASE_CONTEXT_ID")
    if ctx_id:
        print(f"==> reusing existing context {ctx_id} (refreshing login)")
    else:
        ctx = bb.contexts.create()
        ctx_id = ctx.id
        print(f"==> created context {ctx_id}")
    _persist_ctx_id(ctx_id)  # save NOW, before anything can crash

    session = bb.sessions.create(
        browser_settings={"context": {"id": ctx_id, "persist": True}},
    )
    print(f"==> session {session.id} started")

    live = _live_view_url(bb, session.id)
    print("\n" + "=" * 70)
    print("STEP 1 — open this live-view URL in your normal browser:")
    print(f"\n    {live or '(fetch failed — see Browserbase dashboard > Sessions)'}\n")
    print("STEP 2 — in that window, log into wandb as the neosigma account.")
    print("STEP 3 — once you SEE your wandb dashboard, return here and press ENTER.")
    print("         Keep the live-view tab OPEN.")
    print("=" * 70 + "\n")

    with sync_playwright() as p:
        browser = _connect(p, session.connect_url)
        browser.contexts[0].pages[0].goto(WANDB_LOGIN, wait_until="domcontentloaded")

        input("Press ENTER after you've logged into wandb... ")

        # The idle CDP socket likely dropped during login; reconnect to the
        # still-live session rather than crashing on a dead handle.
        try:
            wandb_cookies = _wandb_cookies(browser)
        except Exception as e:  # noqa: BLE001
            print(f"  (control socket dropped: {type(e).__name__}; reconnecting…)")
            try:
                browser = _connect(p, session.connect_url)
                wandb_cookies = _wandb_cookies(browser)
            except Exception as e2:  # noqa: BLE001
                print(f"  (reconnect failed: {e2})")
                print("  The session may have ended. persist:true still saves cookies on")
                print("  session end — run `--verify` to check if the login stuck.")
                wandb_cookies = []

        names = sorted({c["name"] for c in wandb_cookies})
        print(f"\n==> {len(wandb_cookies)} wandb cookie(s) captured: {names or 'NONE'}")
        if not wandb_cookies:
            print("    WARNING: no wandb cookies seen here — run `--verify` to confirm,")
            print("    and if still empty, re-run and reach the dashboard before ENTER.")
        try:
            browser.close()  # session end -> persist:true writes cookies into the context
        except Exception:
            pass

    print("==> waiting 5s for Browserbase to sync the context...")
    time.sleep(5)
    print("\n" + "=" * 70)
    print(f"DONE. BROWSERBASE_CONTEXT_ID={ctx_id}  (saved to .env)")
    print("Confirm with:  python3 scripts/setup_browserbase_context.py --verify")
    print("=" * 70)
    return 0


def main() -> int:
    api_key = os.environ.get("BROWSERBASE_API_KEY")
    if not api_key:
        print("ERROR: BROWSERBASE_API_KEY not set. Run: set -a; source .env; set +a")
        return 1
    bb = Browserbase(api_key=api_key)
    if "--verify" in sys.argv[1:]:
        return verify(bb)
    return setup(bb)


if __name__ == "__main__":
    sys.exit(main())

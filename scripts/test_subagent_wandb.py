#!/usr/bin/env python3
"""Quick test: prove the Browserbase wandb context works for a SUB-AGENT.

Simulates exactly what a sub-agent does in its container: with ONLY
BROWSERBASE_API_KEY + BROWSERBASE_CONTEXT_ID (no wandb credentials at all), open a
READ-ONLY (persist:false) Browserbase cloud session that inherits the saved
cookies, load an authenticated wandb page, screenshot it, and assert we landed
logged-in (not bounced to /login).

This is the sub-agent contract: it never holds wandb creds — it only references
the context id (injected as a Modal/container secret) to view live run pages.

Usage:
    set -a; source .env; set +a
    python3 scripts/test_subagent_wandb.py [wandb_url] [--out PATH]
        wandb_url default: https://wandb.ai/home   (pass a real run URL to screenshot it)
Exit 0 = logged-in screenshot captured; non-zero = not logged in / error.
"""
from __future__ import annotations

import os
import sys

from browserbase import Browserbase
from playwright.sync_api import sync_playwright


def main() -> int:
    api = os.environ.get("BROWSERBASE_API_KEY")
    ctx = os.environ.get("BROWSERBASE_CONTEXT_ID")
    if not api or not ctx:
        print("ERROR: need BROWSERBASE_API_KEY + BROWSERBASE_CONTEXT_ID "
              "(run: set -a; source .env; set +a)")
        return 1

    args = [a for a in sys.argv[1:]]
    out = "/tmp/wandb_subagent_test.png"
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1]
        del args[i:i + 2]
    url = args[0] if args else "https://wandb.ai/home"

    bb = Browserbase(api_key=api)
    # READ-ONLY reuse: persist:false — the sub-agent inherits cookies, writes nothing back.
    session = bb.sessions.create(
        browser_settings={"context": {"id": ctx, "persist": False}},
    )
    print(f"==> session {session.id} reusing context {ctx} (persist:false, read-only)")

    final = title = ""
    n_cookies = 0
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(session.connect_url)
        bctx = browser.contexts[0]
        page = bctx.pages[0] if bctx.pages else bctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3500)  # let the dashboard/run page render (wandb never network-idles)
        final, title = page.url, page.title()
        n_cookies = len([c for c in bctx.cookies() if "wandb" in (c.get("domain") or "")])
        page.screenshot(path=out, full_page=True)
        browser.close()

    logged_in = "/login" not in final and n_cookies > 0
    print(f"==> requested:  {url}")
    print(f"==> landed:     {final}")
    print(f"==> page title: {title}")
    print(f"==> wandb cookies inherited from context: {n_cookies}")
    print(f"==> screenshot: {out}")
    print("\n" + ("✅ SUB-AGENT CAN VIEW AUTHENTICATED WANDB via the context (logged in)."
                  if logged_in else
                  "❌ NOT logged in (redirected to /login or no cookies) — re-run setup."))
    return 0 if logged_in else 2


if __name__ == "__main__":
    sys.exit(main())

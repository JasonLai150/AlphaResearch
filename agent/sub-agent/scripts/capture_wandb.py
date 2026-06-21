#!/usr/bin/env python3
"""Capture THIS sub-agent's wandb run with the Browserbase smart agent (Stagehand).

Two layers, both anchored to the SAME deterministic run URL (derived from the job
id by wandb_run.py), so even with many sub-agents running at once each one only ever
touches its OWN run:

  1. PNG (deterministic, always): a Browserbase session reusing the shared login
     context (read-only) navigates to the run URL and full-page screenshots it into
     the artifacts dir -> the runner ships it to GCS and back to the parent.
  2. Smart analysis (best-effort): Stagehand's agent drives the same run URL to read
     the learning curves and `extract` final-performance metrics as structured JSON.
     Skipped cleanly if BROWSERBASE_PROJECT_ID isn't set or Stagehand errors — the
     PNG still comes back.

The smart agent never PICKS the run (that's the wrong-run footgun on a shared login);
it only analyzes the URL we hand it. Run identity is owned by wandb_run.py.

Usage (one Bash call; no args needed):
    python3 scripts/capture_wandb.py [--url URL] [--name FILE.png] [--no-smart]
Exit 0 if a screenshot was captured; non-zero on failure (never required for the run).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wandb_run import run_identity, run_url_path  # noqa: E402

GOAL = ("Look at this Weights & Biases run page. Inspect the training/eval learning "
        "curves and report the final performance, whether the metric is still "
        "improving or has plateaued, and anything notable.")
EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "final_metric": {"type": "string"},
        "trend": {"type": "string"},
        "converged": {"type": "boolean"},
        "notes": {"type": "string"},
    },
}


def resolve_run_url(cli_url: str | None) -> str:
    """Deterministic: explicit --url > $WANDB_RUN_URL > the file the trainer wrote
    (init_wandb) > the convention derived from the job/session ids."""
    if cli_url:
        return cli_url
    env = os.environ.get("WANDB_RUN_URL")
    if env:
        return env
    f = run_url_path()
    if f.exists():
        u = f.read_text().strip()
        if u:
            return u
    return run_identity()["url"]


def artifacts_dir() -> Path:
    base = os.environ.get("ALPHA_DISPATCH_DIR", "/workspace/.dispatched")
    jid = os.environ.get("ALPHA_JOB_ID", "local")
    d = Path(base) / "artifacts" / jid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _playwright_screenshot(api_key: str, ctx_id: str, url: str, out_path: Path,
                           wait_ms: int = 4000) -> str:
    """Deterministic PNG of the run page. Returns the landed URL. Verified path."""
    from browserbase import Browserbase
    from playwright.sync_api import sync_playwright

    bb = Browserbase(api_key=api_key)
    session = bb.sessions.create(
        browser_settings={"context": {"id": ctx_id, "persist": False}},
    )
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(session.connect_url)
        bctx = browser.contexts[0]
        page = bctx.pages[0] if bctx.pages else bctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(wait_ms)
        landed = page.url
        page.screenshot(path=str(out_path), full_page=True)
        browser.close()
    return landed


def _stagehand_analyze(api_key: str, project_id: str, ctx_id: str, url: str,
                       model: str) -> dict | None:
    """Best-effort smart analysis via Stagehand. Returns a dict or None. Never raises."""
    if not project_id:
        return None
    try:
        from stagehand import Stagehand

        client = Stagehand(
            browserbase_api_key=api_key,
            browserbase_project_id=project_id,
            model_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )
        start = client.sessions.start(
            model_name=model,
            browserbase_session_create_params={
                "browser_settings": {"context": {"id": ctx_id, "persist": False}},
            },
        )
        data = getattr(start, "data", None)
        sh_id = (getattr(data, "session_id", None) or getattr(data, "id", None)
                 or getattr(start, "session_id", None))
        if not sh_id:
            return {"error": "could not resolve stagehand session id"}
        client.sessions.navigate(sh_id, url=url)
        agent = client.sessions.execute(
            sh_id,
            agent_config={"provider": "anthropic", "mode": "hybrid"},
            execute_options={"instruction": GOAL, "max_steps": 12},
        )
        info = client.sessions.extract(
            sh_id, instruction="final performance metrics for this run",
            schema=EXTRACT_SCHEMA,
        )
        client.sessions.end(sh_id)
        return {
            "agent": getattr(agent, "data", None) or {},
            "metrics": getattr(info, "data", None) or {},
        }
    except Exception as e:  # noqa: BLE001 — smart layer is best-effort
        return {"error": f"{type(e).__name__}: {e}"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=None)
    ap.add_argument("--name", default="wandb_run.png")
    ap.add_argument("--no-smart", action="store_true")
    ap.add_argument("--wait-ms", type=int, default=4000)
    ap.add_argument("--model", default=os.environ.get("ALPHA_MODEL", "claude-sonnet-4-6"))
    a = ap.parse_args(argv if argv is not None else sys.argv[1:])

    api_key = os.environ.get("BROWSERBASE_API_KEY")
    ctx_id = os.environ.get("BROWSERBASE_CONTEXT_ID")
    url = resolve_run_url(a.url)
    if not url:
        print("capture_wandb: no run URL (set WANDB_ENTITY or pass --url)", file=sys.stderr)
        return 2
    if not api_key or not ctx_id:
        print("capture_wandb: BROWSERBASE_API_KEY/CONTEXT_ID not set", file=sys.stderr)
        return 3

    out = artifacts_dir() / a.name
    try:
        landed = _playwright_screenshot(api_key, ctx_id, url, out, a.wait_ms)
    except Exception as e:  # noqa: BLE001
        print(f"capture_wandb: screenshot failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 5

    smart = None
    if not a.no_smart:
        smart = _stagehand_analyze(
            api_key, os.environ.get("BROWSERBASE_PROJECT_ID", ""), ctx_id, url, a.model
        )

    record = {
        "run_url": url,
        "landed": landed,
        "screenshot": str(out),
        "logged_in": "/login" not in landed,
        "job_id": run_identity()["job_id"],
        "smart": smart,
    }
    # Write the smart analysis next to the PNG so it ships back too.
    if smart and "error" not in smart:
        (artifacts_dir() / "wandb_summary.json").write_text(json.dumps(smart, indent=2))
    print(json.dumps(record))
    if "/login" in landed:
        print("capture_wandb: landed on /login — context not logged in", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())

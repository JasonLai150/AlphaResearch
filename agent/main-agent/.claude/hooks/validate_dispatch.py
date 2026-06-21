#!/usr/bin/env python3
"""PreToolUse hook: re-validate the dispatch payload before Bash runs it.

Claude Code invokes this script for every Bash tool call (matcher in
.claude/settings.json). We early-exit (allow) for any Bash command that isn't
the dispatch script. For the dispatch script we re-parse the --plan JSON file
and validate against scripts/schemas.ResearchPlan, so a malformed plan is
rejected BEFORE the subprocess runs.

Stdin (Claude Code Hooks v1 PreToolUse payload):
    {
      "session_id": "...",
      "transcript_path": "...",
      "cwd": "...",
      "tool_name": "Bash",
      "tool_input": {"command": "...", "description": "..."}
    }

Exit codes:
  0 = allow the tool call
  2 = block (stderr is shown to the model so it can fix the call)
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

# Make sibling scripts/schemas.py importable. .claude/hooks/ is two levels
# below the agent root; scripts/ is a sibling of .claude/.
_AGENT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _AGENT_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


DISPATCH_SCRIPT_NAME = "dispatch_subagent.py"


def _read_payload() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}


def _extract_plan_path_and_idea(command: str) -> tuple[str | None, str | None]:
    """Pull --plan and --idea-id values out of a shell command string.

    Handles `--plan X`, `--plan=X`, `--idea-id X`, `--idea-id=X`. Tolerates
    arbitrary surrounding tokens (env vars, python -u, cwd changes, etc).
    Returns (None, None) when the command does not invoke our dispatch script.
    """
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return None, None
    if not any(DISPATCH_SCRIPT_NAME in t for t in tokens):
        return None, None

    plan_path: str | None = None
    idea_id: str | None = None
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--plan" and i + 1 < len(tokens):
            plan_path = tokens[i + 1]
            i += 2
            continue
        if tok.startswith("--plan="):
            plan_path = tok.split("=", 1)[1]
            i += 1
            continue
        if tok == "--idea-id" and i + 1 < len(tokens):
            idea_id = tokens[i + 1]
            i += 2
            continue
        if tok.startswith("--idea-id="):
            idea_id = tok.split("=", 1)[1]
            i += 1
            continue
        i += 1
    return plan_path, idea_id


def _block(reason: str) -> None:
    print(reason, file=sys.stderr)
    sys.exit(2)


def main() -> None:
    payload = _read_payload()
    if payload.get("tool_name") != "Bash":
        sys.exit(0)
    command = (payload.get("tool_input") or {}).get("command") or ""
    if DISPATCH_SCRIPT_NAME not in command:
        sys.exit(0)

    plan_path_str, idea_id = _extract_plan_path_and_idea(command)
    if not plan_path_str:
        _block(
            f"dispatch hook: {DISPATCH_SCRIPT_NAME} was invoked without `--plan <path>`. "
            "Always pass the plan JSON path explicitly."
        )
    if not idea_id:
        _block(
            f"dispatch hook: {DISPATCH_SCRIPT_NAME} was invoked without `--idea-id <id>`. "
            "Pass exactly one idea id per call."
        )

    # Resolve relative to the agent cwd (Claude Code passes cwd in payload).
    cwd = Path(payload.get("cwd") or ".")
    plan_path = Path(plan_path_str)
    if not plan_path.is_absolute():
        plan_path = (cwd / plan_path).resolve()

    if not plan_path.exists():
        _block(f"dispatch hook: plan file not found at {plan_path}")

    try:
        raw = json.loads(plan_path.read_text())
    except json.JSONDecodeError as e:
        _block(f"dispatch hook: plan file is not valid JSON: {e}")

    try:
        # Imported here so a missing pydantic gives a clear error.
        from pydantic import ValidationError
        from schemas import ResearchPlan
    except ImportError as e:
        _block(f"dispatch hook: cannot import schemas (install pydantic): {e}")

    try:
        plan = ResearchPlan.model_validate(raw)
    except ValidationError as e:
        # Pretty print the first 5 errors so the agent gets a clear repair signal.
        errs = e.errors(include_url=False)[:5]
        summary = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in errs)
        _block(f"dispatch hook: ResearchPlan invalid: {summary}")

    if plan.find_idea(idea_id) is None:
        valid = [i.id for i in plan.ideas]
        _block(
            f"dispatch hook: idea_id={idea_id!r} not in plan {plan.id}. "
            f"Valid: {valid}"
        )

    # Belt-and-suspenders: refuse if the agent already dispatched this idea.
    out_dir = (cwd / ".dispatched").resolve()
    if out_dir.exists():
        for p in out_dir.glob("*.json"):
            if p.name.endswith(".result.json"):
                continue
            try:
                rec = json.loads(p.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if rec.get("idea_id") == idea_id and rec.get("plan", {}).get("id") == plan.id:
                _block(
                    f"dispatch hook: idea_id={idea_id!r} already dispatched in this plan "
                    f"(job_id={rec.get('job_id')}). Do not re-dispatch the same idea."
                )

    # Best-effort short summary printed to the agent on success.
    print(
        f"dispatch hook: validated plan={plan.id} idea={idea_id} "
        f"(diversity_tag={plan.find_idea(idea_id).diversity_tag.value})"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()

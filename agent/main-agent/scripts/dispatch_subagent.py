#!/usr/bin/env python3
"""Deterministic dispatch script. The main agent invokes this via Bash.

Usage:
    python3 scripts/dispatch_subagent.py --plan <plan.json> --idea-id <id> [--out-dir ./.dispatched]

What it does:
  1. Loads + validates the ResearchPlan JSON file (scripts/schemas.py).
  2. Confirms the idea_id exists in the plan.
  3. Generates a job_id.
  4. Writes a dispatch record to <out-dir>/<job_id>.json. The record contains
     the whole plan plus the assigned idea_id — the sub-agent runner copies
     this file into the sub-agent container as /workspace/job.json.
  5. Prints one JSON line to stdout: {"job_id": "...", "status": "dispatched",
     "out_path": "..."}.

The actual container/VM spawn is NOT done here — that's the runner's job.
This script is the deterministic seam between the agent and the runner: it
guarantees that anything reaching the runner has already passed schema +
consistency validation.

Exit codes:
  0 = dispatched successfully (json on stdout)
  1 = invalid arguments or filesystem error
  2 = schema / consistency validation failed (reason on stderr)
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Import the schemas from this same scripts/ folder.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from pydantic import ValidationError  # noqa: E402

from schemas import ResearchPlan  # noqa: E402


def _die(code: int, msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(description="Dispatch one sub-agent for one idea.")
    ap.add_argument("--plan", required=True, type=Path, help="path to plan.json")
    ap.add_argument("--idea-id", required=True, type=str, help="id of the idea to dispatch")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("./.dispatched"),
        help="where to write the dispatch record (default ./.dispatched)",
    )
    ap.add_argument(
        "--parent-job-id",
        type=str,
        default="root",
        help="job id of the main agent (default 'root' for local runs)",
    )
    args = ap.parse_args(argv)

    if not args.plan.exists():
        _die(1, f"plan file not found: {args.plan}")
    try:
        raw = json.loads(args.plan.read_text())
    except json.JSONDecodeError as e:
        _die(1, f"plan file is not valid JSON: {e}")

    try:
        plan = ResearchPlan.model_validate(raw)
    except ValidationError as e:
        _die(2, f"ResearchPlan invalid:\n{e}")

    idea = plan.find_idea(args.idea_id)
    if idea is None:
        _die(
            2,
            f"idea_id={args.idea_id!r} not in plan {plan.id}. "
            f"Valid ids: {[i.id for i in plan.ideas]}",
        )

    job_id = f"j_{uuid.uuid4().hex[:12]}"
    record = {
        "job_id": job_id,
        "parent_job_id": args.parent_job_id,
        "kind": "agent",
        "created_at": datetime.now(UTC).isoformat(),
        "plan": plan.model_dump(mode="json"),
        "idea_id": idea.id,
        "strategy": f"{idea.diversity_tag.value}: {idea.title}",
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"{job_id}.json"
    out_path.write_text(json.dumps(record, indent=2, sort_keys=True))

    print(json.dumps({
        "job_id": job_id,
        "status": "dispatched",
        "idea_id": idea.id,
        "diversity_tag": idea.diversity_tag.value,
        "out_path": str(out_path),
    }))


if __name__ == "__main__":
    main(sys.argv[1:])

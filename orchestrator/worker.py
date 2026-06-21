"""Depth-0 session consumer — SUPERSEDED by the runner.

Previously this consumed `sessions:queue` and ran the in-process SDK `run_agent`.
That runtime was replaced by the Claude Code harness, and launching the depth-0
main-agent container is now the RUNNER's job. This stub stays as documentation of
the seam and intentionally does NOT consume `sessions:queue`, so it can't steal
messages the runner needs.

Contract for the runner: consume `store.SESSIONS_QUEUE`; for each `session_id`,
resolve the root job (`store.get_root_job`) and launch the main-agent harness.
"""

from __future__ import annotations


async def run_worker() -> None:
    raise NotImplementedError(
        "Depth-0 execution moved to the runner; this worker no longer consumes "
        "sessions:queue. See module docstring for the runner contract."
    )


if __name__ == "__main__":
    print(__doc__)

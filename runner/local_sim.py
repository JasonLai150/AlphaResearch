"""Local development backend — drive a realistic research run without Cloud Run/Modal.

When ``ALPHA_LOCAL_SIM=true`` the API starts :func:`local_sim_loop`, which tails
the sessions queue and, for each new session, plays a scripted run end to end —
status / spawn / metric / summary / artifact events plus transcript messages —
straight into Redis, exactly as the real runner + agents would. This lets the
full web app (create session → live SSE → tree / transcript / charts / artifacts)
work locally with zero cloud credentials.

NOT used in production: the flag defaults to false, and this module is only
imported when it is true, so it never affects the real runner or the test suite.
"""

from __future__ import annotations

import asyncio
import re

from infra import store
from infra.schemas import (
    EventEnvelope,
    EventType,
    Job,
    JobKind,
    JobStatus,
    Message,
    RunResult,
)

# Base pacing (seconds). Kept short so a run streams visibly but finishes in ~10s.
_TICK = 0.7

# Typewriter pacing for assistant narration. Short so a message types out in
# ~0.5-1s without dragging the ~10s scripted run.
_TOKEN_TICK = 0.04


async def _emit(sid, jid, depth, type_, payload, parent=None) -> None:
    await store.emit_event(
        EventEnvelope(
            session_id=sid,
            job_id=jid,
            parent_job_id=parent,
            depth=depth,
            type=type_,
            payload=payload,
        )
    )


async def _msg(sid, jid, role, content) -> None:
    # Assistant narration types out as `token` deltas (typewriter). User/tool/
    # system lines stay atomic `log` events.
    if role == "assistant":
        await _stream_assistant(sid, jid, content)
        return
    await store.append_message(
        Message(session_id=sid, job_id=jid, role=role, content=content)
    )
    await _emit(sid, jid, 0, EventType.log, {"role": role, "content": content})


def _chunk_text(content: str, group: int = 3) -> list[str]:
    """Split `content` into ~`group`-word chunks, preserving trailing whitespace
    so that ``"".join(chunks) == content`` (deltas concatenate back exactly)."""
    words = re.findall(r"\S+\s*", content)
    if not words:
        return []
    return ["".join(words[i : i + group]) for i in range(0, len(words), group)]


async def _stream_assistant(sid, jid, content) -> None:
    """Emit `content` as a sequence of token deltas (last one final), then persist
    the whole message for the /full snapshot. Mirrors what stream_relay does for
    the real agent."""
    msg_id = store.new_id("m")
    chunks = _chunk_text(content)
    last = len(chunks) - 1
    for i, chunk in enumerate(chunks):
        await _emit(
            sid, jid, 0, EventType.token,
            {"msg_id": msg_id, "role": "assistant", "delta": chunk, "final": i == last},
        )
        await asyncio.sleep(_TOKEN_TICK)
    await store.append_message(
        Message(session_id=sid, job_id=jid, role="assistant", content=content)
    )


def _reward_svg(points: list[tuple[int, float]], color: str = "#ff7a17") -> bytes:
    """A small self-contained reward-vs-steps line chart for the artifact panel."""
    W, H, pad = 320, 150, 26
    xs = [p[0] for p in points]
    xmin, xmax = min(xs), max(xs)
    span = (xmax - xmin) or 1

    def X(s: int) -> float:
        return pad + (s - xmin) / span * (W - 2 * pad)

    def Y(r: float) -> float:
        return (H - pad) - r * (H - 2 * pad)

    line = " ".join(f"{X(s):.1f},{Y(r):.1f}" for s, r in points)
    dots = "".join(
        f'<circle cx="{X(s):.1f}" cy="{Y(r):.1f}" r="2.5" fill="{color}"/>'
        for s, r in points
    )
    grid = "".join(
        f'<line x1="{pad}" y1="{Y(g):.1f}" x2="{W - pad}" y2="{Y(g):.1f}" '
        f'stroke="#212327" stroke-width="1"/>'
        for g in (0.0, 0.5, 1.0)
    )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}">'
        f'<rect width="{W}" height="{H}" rx="8" fill="#191919" stroke="#212327"/>'
        f"{grid}"
        f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2"/>'
        f"{dots}"
        f'<text x="{pad}" y="16" fill="#7d8187" font-family="monospace" '
        f'font-size="9">eval/reward</text></svg>'
    )
    return svg.encode()


# Three research directions (mirrors the dashboard copy). X/Y run; Z stays queued.
_IDEAS = [
    ("X", "Curiosity (ICM)", "exploration", "#ff7a17",
     [(10000, 0.18), (20000, 0.34), (30000, 0.52), (40000, 0.70), (50000, 0.81)]),
    ("Y", "Subgoal shaping", "reward_shaping", "#a0c3ec",
     [(10000, 0.15), (20000, 0.30), (30000, 0.45), (40000, 0.57), (50000, 0.64)]),
    ("Z", "GAE-λ sweep", "optimizer", "#c4b5fd", None),
]


async def run_local_sim_session(sid: str) -> None:
    """Play one scripted research run for an existing session."""
    root = await store.get_root_job(sid)
    if not root:
        return
    session = await store.get_session(sid)
    goal = session.goal if session else "Research goal"

    await _msg(sid, root, "user", goal)
    await asyncio.sleep(0.4)
    await store.mark_job_running(root, "local-sim", "local")
    await _emit(sid, root, 0, EventType.status, {"status": "running", "note": "planning"})
    await _msg(
        sid, root, "assistant",
        "Scoped the goal and read the current PPO config. The plateau lines up with "
        "the sparse reward — the policy rarely chains pick-up-key → open-door inside "
        "the episode budget, so the advantage estimates stay noisy. Branching three "
        "independent directions, each isolated in its own worktree.",
    )
    await asyncio.sleep(0.6)

    child: dict[str, str] = {}
    for name, label, tag, _color, _curve in _IDEAS:
        cjid = store.new_id("j")
        child[name] = cjid
        await store.create_job(Job(
            id=cjid, session_id=sid, parent_job_id=root, depth=1, kind=JobKind.agent,
            params={"goal": label, "strategy": tag, "idea_id": f"idea_{name.lower()}"},
            status=JobStatus.queued, backend="local",
        ))
        await _emit(sid, cjid, 1, EventType.spawn,
                    {"kind": "agent", "goal": label, "strategy": tag, "budget_left": 90},
                    parent=root)
        await _msg(sid, root, "assistant", f"Dispatched sub-agent {name} — {label}.")
        await asyncio.sleep(0.35)

    # X and Y start running; Z stays queued (waiting for a runner).
    for name in ("X", "Y"):
        await store.mark_job_running(child[name], f"local-{name}", "local")
        await _emit(sid, child[name], 1, EventType.status,
                    {"status": "running", "note": "pilot: 50k steps × 8 seeds"}, parent=root)

    # Y fans out two experiment seed-runs (depth 2) — exercises a nested tree.
    seeds: list[str] = []
    for s in (1, 2):
        sjid = store.new_id("j")
        seeds.append(sjid)
        await store.create_job(Job(
            id=sjid, session_id=sid, parent_job_id=child["Y"], depth=2,
            kind=JobKind.experiment,
            params={"goal": f"seed {s}", "env_id": "MiniGrid-DoorKey-8x8-v0"},
            status=JobStatus.running, backend="local",
        ))
        await _emit(sid, sjid, 2, EventType.spawn,
                    {"kind": "experiment", "goal": f"seed {s}"}, parent=child["Y"])

    # Stream reward curves for X and Y, interleaved.
    curves = {name: curve for name, _l, _t, _c, curve in _IDEAS if curve}
    for i in range(5):
        for name in ("X", "Y"):
            step, reward = curves[name][i]
            await _emit(sid, child[name], 1, EventType.metric,
                        {"step": step, "reward": reward, "series": "eval/reward"},
                        parent=root)
        await asyncio.sleep(_TICK)

    # Seeds finish.
    for sjid in seeds:
        await store.write_run(RunResult(job_id=sjid, status="done", summary="eval complete",
                                        metrics={"final_reward": 0.80}))
        await store.set_job_status(sjid, JobStatus.done)
        await _emit(sid, sjid, 2, EventType.summary,
                    {"summary": "eval complete", "metrics": {"final_reward": 0.80}},
                    parent=child["Y"])

    # Artifact: X's reward curve.
    await store.put_artifact(
        sid, child["X"], "plot", _reward_svg(curves["X"]), "reward.svg",
        caption="X — eval reward vs steps", content_type="image/svg+xml",
    )

    finals = {
        "X": (0.81, "Curiosity (ICM) cracked the key→door chaining — 0.81 success, "
                    "0.79 on extrinsic-only reward (not farming the bonus)."),
        "Y": (0.64, "Subgoal shaping steady at 0.64 and still climbing."),
    }
    for name in ("X", "Y"):
        rew, summ = finals[name]
        await store.write_run(RunResult(job_id=child[name], status="done", summary=summ,
                                        metrics={"final_reward": rew}))
        await store.set_job_status(child[name], JobStatus.done)
        await _emit(sid, child[name], 1, EventType.summary,
                    {"summary": summ, "metrics": {"final_reward": rew},
                     "reported_status": "done"}, parent=root)
        await asyncio.sleep(0.3)

    await _msg(
        sid, root, "assistant",
        "X (curiosity) is the clear winner at 0.81 vs 0.64 for subgoal shaping, and "
        "extrinsic-only success holds at 0.79 — it's genuinely completing levels. "
        "Recommendation: scale X to the full 2M-step run and fold Y's subgoal shaping "
        "in as an ablation. Z stayed queued.",
    )
    await store.write_run(RunResult(job_id=root, status="done",
                                    summary="X wins (0.81). Scale X; ablate Y."))
    await store.set_job_status(root, JobStatus.done)
    await _emit(sid, root, 0, EventType.summary,
                {"summary": "X wins (0.81). Scale X; ablate Y.",
                 "metrics": {"best_reward": 0.81}})


async def _guarded_run(sid: str) -> None:
    """Run a sim session; on failure, mark the root failed so the UI stops spinning."""
    try:
        await run_local_sim_session(sid)
    except Exception as e:  # noqa: BLE001
        print(f"[local_sim] run failed for {sid}: {e!r}")
        root = await store.get_root_job(sid)
        if root:
            await _emit(sid, root, 0, EventType.status,
                        {"status": "failed", "reason": "local-sim error"})
            # Surface WHY it failed so the UI can show the cause, not just a spinner stop.
            await _emit(sid, root, 0, EventType.error,
                        {"reason": "local-sim error", "message": str(e)})


async def _guarded_reply(sid: str, content: str) -> None:
    try:
        await respond_to_message(sid, content)
    except Exception as e:  # noqa: BLE001
        print(f"[local_sim] reply failed for {sid}: {e!r}")
        root = await store.get_root_job(sid)
        if root:
            # Surface WHY the follow-up failed so the UI can show the cause.
            await _emit(sid, root, 0, EventType.error,
                        {"reason": "local-sim reply error", "message": str(e)})


async def local_sim_loop() -> None:
    """Tail the sessions queue and play a simulated run for each new session."""
    while True:
        try:
            for entry_id, fields in await store.read_stream(
                store.SESSIONS_QUEUE, "0", 50, 2000
            ):
                await store.delete_stream_entry(store.SESSIONS_QUEUE, entry_id)
                sid = fields.get("session_id")
                if sid:
                    asyncio.create_task(_guarded_run(sid))
        except Exception as e:  # noqa: BLE001
            print(f"[local_sim] {e!r}")
            await asyncio.sleep(1.0)


# ---- conversational follow-ups -----------------------------------------

async def respond_to_message(sid: str, content: str) -> None:
    """Answer a user follow-up, grounded in the run's best result. (Production
    routes this to the conversational agent + AMS memory; this is the dev stand-in.)"""
    await asyncio.sleep(0.8)  # brief "thinking"
    root = await store.get_root_job(sid)
    best: float | None = None
    for c in await store.child_statuses(root) if root else []:
        r = (c.get("metrics") or {}).get("final_reward")
        if isinstance(r, (int, float)) and (best is None or r > best):
            best = float(r)
    snippet = content[:80]
    if best is not None:
        reply = (
            f"On “{snippet}” — the strongest direction is at reward {best:.2f}. "
            "I'd scale that to the full run and keep the runner-up as an ablation. "
            "Say the word and I'll launch a focused 2M-step run."
        )
    else:
        reply = (
            f"On “{snippet}” — I can spin up a focused sub-agent to dig into that. "
            "Want me to launch one?"
        )
    await _msg(sid, root or "", "assistant", reply)


async def chat_inbox_loop() -> None:
    """Tail the chat inbox and answer user follow-ups."""
    while True:
        try:
            for entry_id, fields in await store.read_stream(
                store.CHAT_INBOX, "0", 50, 2000
            ):
                await store.delete_stream_entry(store.CHAT_INBOX, entry_id)
                sid = fields.get("session_id")
                if sid:
                    asyncio.create_task(
                        _guarded_reply(sid, fields.get("content", ""))
                    )
        except Exception as e:  # noqa: BLE001
            print(f"[local_sim chat] {e!r}")
            await asyncio.sleep(1.0)

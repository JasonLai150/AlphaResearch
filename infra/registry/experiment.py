"""Experiment execution.

`run_experiment_stub` — fast, dependency-light, deterministic-by-params synthetic
run used locally to exercise the full tree/flow without GPUs or torch.

`run_experiment_real` — the prebaked env+trainer that runs inside the Modal image
(heavy deps imported lazily so this module imports fine in the control plane).
"""

from __future__ import annotations

import hashlib
import io
import math

from infra import store
from infra.schemas import EventEnvelope, EventType, JobStatus, RunResult

# A tiny prebaked registry. The agent picks env_id + trainer; we parameterize.
ENV_REGISTRY = {
    "MiniGrid-Empty-8x8-v0": {"difficulty": 0.2},
    "MiniGrid-DoorKey-8x8-v0": {"difficulty": 0.6},
    "MiniGrid-MultiRoom-N4-S5-v0": {"difficulty": 0.8},
}
TRAINERS = ("ppo", "sac", "dqn")


def _seeded_unit(*parts: str) -> float:
    """Deterministic pseudo-random in [0,1) from the given parts (no global RNG)."""
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


async def run_experiment_stub(job) -> RunResult:
    """Synthetic training run. Different params → different curves, so the agent's
    choices visibly matter in the demo."""
    p = job.params
    env_id = p.get("env_id") or p.get("env") or "MiniGrid-DoorKey-8x8-v0"
    trainer = (p.get("trainer") or "ppo").lower()
    lr = float(p.get("lr", p.get("learning_rate", 3e-4)))
    total_steps = int(p.get("total_steps", 100_000))

    await store.set_job_status(job.id, JobStatus.running)
    await store.emit_event(_status(job, "running", note=f"{trainer} on {env_id}"))

    difficulty = ENV_REGISTRY.get(env_id, {"difficulty": 0.5})["difficulty"]
    # A plausible learning curve: asymptote depends on env difficulty + lr fit.
    lr_fit = math.exp(-((math.log10(lr) + 3.5) ** 2) / 0.5)  # best near lr~3e-4
    asymptote = max(0.05, min(0.98, (1.0 - 0.6 * difficulty) * (0.5 + 0.5 * lr_fit)))
    noise = 0.05 * (_seeded_unit(job.id, trainer) - 0.5)

    n_points = 12
    rewards: list[float] = []
    for i in range(1, n_points + 1):
        frac = i / n_points
        reward = asymptote * (1 - math.exp(-3 * frac)) + noise * frac
        reward = round(max(0.0, min(1.0, reward)), 4)
        rewards.append(reward)
        step = int(total_steps * frac)
        await store.emit_event(
            EventEnvelope(
                session_id=job.session_id,
                job_id=job.id,
                parent_job_id=job.parent_job_id,
                depth=job.depth,
                type=EventType.metric,
                payload={"step": step, "reward": reward, "series": "eval/reward"},
            )
        )

    final_reward = rewards[-1]
    plot = _try_plot(env_id, trainer, total_steps, rewards)
    if plot is not None:
        await store.put_artifact(
            job.session_id, job.id, "plot", plot, "reward_curve.png",
            caption=f"{trainer} / {env_id}", content_type="image/png",
        )

    summary = (
        f"Ran {trainer.upper()} on {env_id} for {total_steps:,} steps "
        f"(lr={lr:g}); final eval reward {final_reward:.3f}."
    )
    run = RunResult(
        job_id=job.id,
        status="done",
        summary=summary,
        metrics={
            "final_reward": final_reward,
            "total_steps": total_steps,
            "lr": lr,
            "trainer": trainer,
            "env_id": env_id,
        },
    )
    await store.write_run(run)
    await store.set_job_status(job.id, JobStatus.done)
    await store.emit_event(
        EventEnvelope(
            session_id=job.session_id,
            job_id=job.id,
            parent_job_id=job.parent_job_id,
            depth=job.depth,
            type=EventType.summary,
            payload={"summary": summary, "metrics": run.metrics},
        )
    )
    return run


def _status(job, status: str, note: str = "") -> EventEnvelope:
    return EventEnvelope(
        session_id=job.session_id,
        job_id=job.id,
        parent_job_id=job.parent_job_id,
        depth=job.depth,
        type=EventType.status,
        payload={"status": status, "note": note},
    )


def _try_plot(env_id: str, trainer: str, total_steps: int, rewards: list[float]) -> bytes | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None
    xs = [int(total_steps * (i + 1) / len(rewards)) for i in range(len(rewards))]
    fig, ax = plt.subplots(figsize=(5, 3.2))
    ax.plot(xs, rewards, marker="o", lw=2)
    ax.set_xlabel("env steps")
    ax.set_ylabel("eval reward")
    ax.set_title(f"{trainer.upper()} · {env_id}")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120)
    plt.close(fig)
    return buf.getvalue()


async def run_experiment_real(job) -> RunResult:  # runs inside the Modal image
    """Prebaked experiment executed in a Modal sandbox.

    P0: delegate to the synthetic run so we first validate the full cloud round-trip
    (spawn -> run in sandbox -> report to the shared Redis -> parent aggregates) on
    CPU, fast, no GPU. Swap in a real short minigrid+PPO train (the image carries
    torch/minigrid/envpool) as a follow-up — it MUST emit the same metric/summary
    events + artifacts so the UI and query_children stay backend-agnostic.
    """
    return await run_experiment_stub(job)

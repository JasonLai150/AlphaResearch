#!/usr/bin/env python3
"""Prebaked, parameterized PPO trainer for sub-agents (demo path).

ONE tested trainer the sub-agent *parameterizes* instead of authoring code each run —
so a dispatched idea is a set of hyperparameter overrides, runtime is deterministic
(~seconds on a small env), and a `result.json` is ALWAYS written (no "no result.json"
crash class). Adapted from `reference/cleanrl/ppo.py` (discrete PPO).

Runs a baseline (defaults) vs intervention (`--intervention "k=v,k=v"`) comparison on a
small discrete env, writes:
  - $ALPHA_WORKSPACE/result.json                              (RunResult the Stop hook POSTs)
  - $ALPHA_DISPATCH_DIR/artifacts/$ALPHA_JOB_ID/metrics.json  (both curves, raw)
  - $ALPHA_DISPATCH_DIR/artifacts/$ALPHA_JOB_ID/training_curves.png

Envs: uses **envpool** (vectorized, fast — supports MiniGrid here) when importable;
falls back to gymnasium + `minigrid` SyncVectorEnv when it isn't (e.g. local macOS),
so the trainer is smoke-testable off-Modal. MiniGrid's Dict obs (image+direction) is
flattened to a vector for a small CPU MLP.

Usage (the sub-agent runs this; no code authoring):
    python3 scripts/train_ppo.py --env MiniGrid-Empty-5x5-v0 --total-steps 50000 \
        --intervention "ent_coef=0.05" --target-metric mean_return_at_50k_steps
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path

import numpy as np

# Knobs an idea may override via --intervention; also the baseline defaults.
TUNABLE = {
    "learning_rate": 2.5e-4,
    "ent_coef": 0.01,
    "num_steps": 128,
    "gamma": 0.99,
    "gae_lambda": 0.95,
    "clip_coef": 0.2,
    "vf_coef": 0.5,
    "max_grad_norm": 0.5,
    "update_epochs": 4,
    "num_minibatches": 4,
    "hidden_size": 64,
    "norm_adv": True,
    "anneal_lr": True,
}
_BOOL = {"norm_adv", "anneal_lr"}


def _coerce(key, val):
    if key in _BOOL:
        return str(val).strip().lower() in ("1", "true", "yes", "on")
    if key in ("num_steps", "update_epochs", "num_minibatches", "hidden_size"):
        return int(float(val))
    return float(val)


def parse_intervention(spec: str) -> dict:
    """'ent_coef=0.05,learning_rate=1e-3' -> {coerced overrides}; only TUNABLE keys."""
    out: dict = {}
    for tok in (spec or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "=" not in tok:
            raise SystemExit(f"[train_ppo] bad --intervention token {tok!r} (need k=v)")
        k, v = tok.split("=", 1)
        k = k.strip()
        if k not in TUNABLE:
            raise SystemExit(f"[train_ppo] unknown knob {k!r}; allowed: {sorted(TUNABLE)}")
        out[k] = _coerce(k, v.strip())
    return out


# ---- envs --------------------------------------------------------------------

def make_vec_envs(env_id: str, num_envs: int, seed: int):
    """Return (envs, backend, n_actions). envpool (fast, prod) or gymnasium fallback."""
    try:
        import envpool  # Linux-only; the Modal sub-agent image has it
        envs = envpool.make(env_id, env_type="gymnasium", num_envs=num_envs, seed=seed)
        n = envs.action_space.n
        return envs, "envpool", int(n)
    except Exception as e:  # noqa: BLE001 — local/macOS or unsupported -> gymnasium
        print(f"[train_ppo] envpool unavailable ({type(e).__name__}); using gymnasium")
        import gymnasium as gym
        try:
            import minigrid  # noqa: F401 — registers MiniGrid-* ids
        except Exception:
            pass
        envs = gym.vector.SyncVectorEnv([lambda: gym.make(env_id) for _ in range(num_envs)])
        n = envs.single_action_space.n
        return envs, "gym", int(n)


def encode_obs(obs, num_envs: int) -> np.ndarray:
    """MiniGrid Dict obs -> float32 (num_envs, D): image/255 flat (+ one-hot direction).
    Generic flat-Box envs (e.g. CartPole) pass straight through."""
    if isinstance(obs, dict):
        img = np.asarray(obs["image"], dtype=np.float32).reshape(num_envs, -1) / 255.0
        parts = [img]
        if "direction" in obs:
            d = np.asarray(obs["direction"]).reshape(num_envs).astype(np.int64)
            oh = np.zeros((num_envs, 4), dtype=np.float32)
            oh[np.arange(num_envs), np.clip(d, 0, 3)] = 1.0
            parts.append(oh)
        return np.concatenate(parts, axis=1).astype(np.float32)
    return np.asarray(obs, dtype=np.float32).reshape(num_envs, -1)


def _reset(envs, seed):
    out = envs.reset(seed=seed) if _accepts_seed(envs) else envs.reset()
    return out[0] if isinstance(out, tuple) else out


def _accepts_seed(envs) -> bool:
    # envpool sets seed at make(); its reset() rejects seed=. gymnasium accepts it.
    return envs.__class__.__module__.startswith("gymnasium")


# ---- model -------------------------------------------------------------------

def build_agent(obs_dim: int, n_actions: int, hidden: int):
    import torch.nn as nn

    def layer_init(layer, std=2 ** 0.5, bias_const=0.0):
        import torch
        torch.nn.init.orthogonal_(layer.weight, std)
        torch.nn.init.constant_(layer.bias, bias_const)
        return layer

    from torch.distributions.categorical import Categorical

    class Agent(nn.Module):
        def __init__(self):
            super().__init__()
            self.critic = nn.Sequential(
                layer_init(nn.Linear(obs_dim, hidden)), nn.Tanh(),
                layer_init(nn.Linear(hidden, hidden)), nn.Tanh(),
                layer_init(nn.Linear(hidden, 1), std=1.0),
            )
            self.actor = nn.Sequential(
                layer_init(nn.Linear(obs_dim, hidden)), nn.Tanh(),
                layer_init(nn.Linear(hidden, hidden)), nn.Tanh(),
                layer_init(nn.Linear(hidden, n_actions), std=0.01),
            )

        def get_value(self, x):
            return self.critic(x)

        def get_action_and_value(self, x, action=None):
            logits = self.actor(x)
            probs = Categorical(logits=logits)
            if action is None:
                action = probs.sample()
            return action, probs.log_prob(action), probs.entropy(), self.critic(x)

    return Agent()


# ---- one training run --------------------------------------------------------

def train_run(env_id: str, total_steps: int, num_envs: int, seed: int, hp: dict) -> dict:
    """Train once with hyperparameters hp; return {curve:[(step,ret)], final_metric, sps}."""
    import torch
    import torch.nn as nn
    import torch.optim as optim

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "4")))
    device = torch.device("cpu")

    num_steps = int(hp["num_steps"])
    batch_size = num_envs * num_steps
    minibatch_size = max(1, batch_size // int(hp["num_minibatches"]))
    num_iterations = max(1, total_steps // batch_size)

    envs, backend, n_actions = make_vec_envs(env_id, num_envs, seed)
    next_obs_raw = _reset(envs, seed)
    next_obs_np = encode_obs(next_obs_raw, num_envs)
    obs_dim = next_obs_np.shape[1]

    agent = build_agent(obs_dim, n_actions, int(hp["hidden_size"])).to(device)
    optimizer = optim.Adam(agent.parameters(), lr=float(hp["learning_rate"]), eps=1e-5)

    obs = torch.zeros((num_steps, num_envs, obs_dim), device=device)
    actions = torch.zeros((num_steps, num_envs), device=device, dtype=torch.long)
    logprobs = torch.zeros((num_steps, num_envs), device=device)
    rewards = torch.zeros((num_steps, num_envs), device=device)
    dones = torch.zeros((num_steps, num_envs), device=device)
    values = torch.zeros((num_steps, num_envs), device=device)

    next_obs = torch.tensor(next_obs_np, device=device)
    next_done = torch.zeros(num_envs, device=device)
    ep_ret = np.zeros(num_envs, dtype=np.float64)
    completed: list[float] = []
    curve: list[tuple[int, float]] = []
    global_step = 0
    t0 = time.time()

    for iteration in range(1, num_iterations + 1):
        if hp["anneal_lr"]:
            frac = 1.0 - (iteration - 1.0) / num_iterations
            optimizer.param_groups[0]["lr"] = frac * float(hp["learning_rate"])

        for step in range(num_steps):
            global_step += num_envs
            obs[step] = next_obs
            dones[step] = next_done
            with torch.no_grad():
                action, logprob, _, value = agent.get_action_and_value(next_obs)
                values[step] = value.flatten()
            actions[step] = action
            logprobs[step] = logprob

            a_np = action.cpu().numpy().astype(np.int64)
            step_out = envs.step(a_np)
            o, r, term, trunc, _info = (list(step_out) + [None] * 5)[:5]
            done = np.logical_or(np.asarray(term), np.asarray(trunc)).astype(np.float32)
            r = np.asarray(r, dtype=np.float64).reshape(num_envs)
            ep_ret += r
            for i in range(num_envs):
                if done[i]:
                    completed.append(float(ep_ret[i]))
                    ep_ret[i] = 0.0
            rewards[step] = torch.tensor(r, device=device, dtype=torch.float32)
            next_obs = torch.tensor(encode_obs(o, num_envs), device=device)
            next_done = torch.tensor(done, device=device)

        # GAE
        with torch.no_grad():
            next_value = agent.get_value(next_obs).reshape(1, -1)
            advantages = torch.zeros_like(rewards, device=device)
            lastgaelam = 0
            for t in reversed(range(num_steps)):
                if t == num_steps - 1:
                    nextnonterminal = 1.0 - next_done
                    nextvalues = next_value
                else:
                    nextnonterminal = 1.0 - dones[t + 1]
                    nextvalues = values[t + 1]
                delta = rewards[t] + hp["gamma"] * nextvalues * nextnonterminal - values[t]
                advantages[t] = lastgaelam = (
                    delta + hp["gamma"] * hp["gae_lambda"] * nextnonterminal * lastgaelam
                )
            returns = advantages + values

        b_obs = obs.reshape(-1, obs_dim)
        b_logprobs = logprobs.reshape(-1)
        b_actions = actions.reshape(-1)
        b_advantages = advantages.reshape(-1)
        b_returns = returns.reshape(-1)

        b_inds = np.arange(batch_size)
        for _epoch in range(int(hp["update_epochs"])):
            np.random.shuffle(b_inds)
            for start in range(0, batch_size, minibatch_size):
                mb = b_inds[start:start + minibatch_size]
                _, newlogprob, entropy, newvalue = agent.get_action_and_value(
                    b_obs[mb], b_actions[mb])
                logratio = newlogprob - b_logprobs[mb]
                ratio = logratio.exp()
                mb_adv = b_advantages[mb]
                if hp["norm_adv"]:
                    mb_adv = (mb_adv - mb_adv.mean()) / (mb_adv.std() + 1e-8)
                pg_loss1 = -mb_adv * ratio
                pg_loss2 = -mb_adv * torch.clamp(ratio, 1 - hp["clip_coef"], 1 + hp["clip_coef"])
                pg_loss = torch.max(pg_loss1, pg_loss2).mean()
                newvalue = newvalue.view(-1)
                v_loss = 0.5 * ((newvalue - b_returns[mb]) ** 2).mean()
                entropy_loss = entropy.mean()
                loss = pg_loss - hp["ent_coef"] * entropy_loss + v_loss * hp["vf_coef"]
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(agent.parameters(), hp["max_grad_norm"])
                optimizer.step()

        recent = float(np.mean(completed[-50:])) if completed else 0.0
        curve.append((global_step, round(recent, 4)))

    try:
        envs.close()
    except Exception:  # noqa: BLE001
        pass
    final_metric = float(np.mean(completed[-50:])) if completed else 0.0
    sps = int(global_step / max(1e-6, time.time() - t0))
    return {"curve": curve, "final_metric": round(final_metric, 4),
            "n_episodes": len(completed), "global_steps": global_step, "sps": sps,
            "backend": backend}


# ---- outputs -----------------------------------------------------------------

def _artifacts_dir() -> Path:
    base = Path(os.environ.get("ALPHA_DISPATCH_DIR", "/workspace/.dispatched"))
    jid = os.environ.get("ALPHA_JOB_ID", "local")
    d = base / "artifacts" / jid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _plot(adir: Path, base: dict, interv: dict, metric: str) -> str | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        return None
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2))
    for label, run in (("baseline", base), ("intervention", interv)):
        xs = [c[0] for c in run["curve"]]
        ys = [c[1] for c in run["curve"]]
        ax1.plot(xs, ys, marker="o", lw=2, label=label)
    ax1.set_xlabel("env steps")
    ax1.set_ylabel("mean episodic return")
    ax1.set_title("Training Curves: baseline vs intervention")
    ax1.grid(alpha=0.3)
    ax1.legend()
    ax2.bar(["baseline", "intervention"], [base["final_metric"], interv["final_metric"]],
            color=["#4C78A8", "#F58518"])
    ax2.set_ylabel(metric)
    ax2.set_title("Final " + metric)
    ax2.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    out = adir / "training_curves.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return str(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default="MiniGrid-Empty-5x5-v0")
    ap.add_argument("--total-steps", type=int, default=50_000)
    ap.add_argument("--num-envs", type=int,
                    default=int(os.environ.get("ALPHA_NUM_ENVS", "8")))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--intervention", default="", help='knob overrides "k=v,k=v"')
    ap.add_argument("--target-metric", default="mean_return")
    ap.add_argument("--idea-id", default=os.environ.get("ALPHA_IDEA_ID", ""))
    a = ap.parse_args()

    overrides = parse_intervention(a.intervention)
    baseline_hp = dict(TUNABLE)
    interv_hp = {**TUNABLE, **overrides}
    print(f"[train_ppo] env={a.env} steps={a.total_steps} num_envs={a.num_envs} "
          f"intervention={overrides or '(none)'}")

    t0 = time.time()
    if overrides:
        base = train_run(a.env, a.total_steps, a.num_envs, a.seed, baseline_hp)
        interv = train_run(a.env, a.total_steps, a.num_envs, a.seed, interv_hp)
    else:
        base = train_run(a.env, a.total_steps, a.num_envs, a.seed, baseline_hp)
        interv = base
    wall = int(time.time() - t0)

    metric = a.target_metric
    delta = round(interv["final_metric"] - base["final_metric"], 4)
    adir = _artifacts_dir()
    (adir / "metrics.json").write_text(json.dumps(
        {"env": a.env, "total_steps": a.total_steps, "num_envs": a.num_envs,
         "baseline": base, "intervention": interv, "intervention_knobs": overrides}, indent=2))
    plot_path = _plot(adir, base, interv, metric)

    metrics = {
        metric: interv["final_metric"],
        f"{metric}_baseline": base["final_metric"],
        "delta_vs_baseline": delta,
        "n_seeds": 1,
        "wall_clock_seconds": wall,
        "global_steps": interv["global_steps"],
        "steps_per_sec": interv["sps"],
        "env_backend": interv["backend"],
    }
    summary = (f"Trained PPO on {a.env} for {interv['global_steps']:,} steps "
               f"({interv['backend']}). Baseline {metric}={base['final_metric']:.3f}; "
               f"intervention ({overrides or 'none'}) {metric}={interv['final_metric']:.3f}; "
               f"delta={delta:+.3f}.")
    result = {
        "job_id": os.environ.get("ALPHA_JOB_ID", "local"),
        "idea_id": a.idea_id,
        "status": "done",
        "summary": summary,
        "metrics": metrics,
        "validated": bool(interv["n_episodes"] > 0),
        "validation_reasoning": (
            f"{interv['n_episodes']} episodes completed; baseline+intervention trained "
            f"identically except the knob(s) {overrides or 'none'} on a frozen scaffold."),
        "artifacts": [p.name for p in (adir.iterdir()) if p.is_file()],
    }
    ws = Path(os.environ.get("ALPHA_WORKSPACE", "/workspace"))
    try:
        (ws / "result.json").write_text(json.dumps(result, indent=2))
    except OSError:
        (Path.cwd() / "result.json").write_text(json.dumps(result, indent=2))
    print(f"[train_ppo] DONE {summary} (wall={wall}s, plot={plot_path})")
    print(json.dumps({"metrics": metrics, "artifacts": result["artifacts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

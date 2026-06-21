"""Reference: PPO on MiniGrid via envpool (CPU, single-file).

BACKGROUND READING ONLY. Sub-agents do not author or adapt training code — they run
the prebaked `scripts/train_ppo.py` with knob overrides (see CLAUDE.md). This file is
the clearest single-file read for how MiniGrid+envpool training works: the bridge
that `ppo.py` (discrete, but gym SyncVectorEnv) and `ppo_atari_envpool.py` (envpool,
but Atari CNN) don't show directly.

What it shows that the other references don't:
  * envpool MiniGrid dict obs: {"direction": (N,), "image": (N,7,7,3) uint8,
    "mission": ...}. We encode image (flattened, scaled) + direction → a small MLP.
  * gymnasium 5-tuple step + envpool auto-reset, with episode-return tracking
    (cumulative reward per env, recorded on done) → the target metric.
  * CPU-sized small net + reads ALPHA_NUM_ENVS so envpool actually vectorizes.

Run:
    python ppo_minigrid_envpool.py --env-id MiniGrid-DoorKey-8x8-v0 --total-timesteps 50000

Prints rolling + final mean episodic return (== mean_return_at_<budget>_steps).
"""

from __future__ import annotations

import argparse
import os
import time
from collections import deque

import envpool
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.distributions.categorical import Categorical


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--env-id", type=str, default="MiniGrid-DoorKey-8x8-v0")
    p.add_argument("--total-timesteps", type=int, default=50_000)
    p.add_argument("--num-envs", type=int, default=int(os.environ.get("ALPHA_NUM_ENVS", "64")))
    p.add_argument("--num-steps", type=int, default=128)       # rollout_length
    p.add_argument("--learning-rate", type=float, default=3e-4)
    p.add_argument("--gamma", type=float, default=0.99)
    p.add_argument("--gae-lambda", type=float, default=0.95)
    p.add_argument("--num-minibatches", type=int, default=4)
    p.add_argument("--update-epochs", type=int, default=4)
    p.add_argument("--clip-coef", type=float, default=0.2)
    p.add_argument("--ent-coef", type=float, default=0.01)
    p.add_argument("--vf-coef", type=float, default=0.5)
    p.add_argument("--max-grad-norm", type=float, default=0.5)
    p.add_argument("--seed", type=int, default=1)
    return p.parse_args()


def encode(obs: dict) -> np.ndarray:
    """envpool MiniGrid dict obs -> float32 (N, 7*7*3 + 1). Image scaled, direction appended."""
    img = np.asarray(obs["image"], dtype=np.float32).reshape(obs["image"].shape[0], -1) / 10.0
    direction = np.asarray(obs["direction"], dtype=np.float32).reshape(-1, 1) / 3.0
    return np.concatenate([img, direction], axis=1)


def layer_init(layer: nn.Linear, std: float = np.sqrt(2)) -> nn.Linear:
    nn.init.orthogonal_(layer.weight, std)
    nn.init.constant_(layer.bias, 0.0)
    return layer


class Agent(nn.Module):
    def __init__(self, obs_dim: int, n_actions: int):
        super().__init__()
        self.critic = nn.Sequential(
            layer_init(nn.Linear(obs_dim, 128)), nn.Tanh(),
            layer_init(nn.Linear(128, 128)), nn.Tanh(),
            layer_init(nn.Linear(128, 1), std=1.0),
        )
        self.actor = nn.Sequential(
            layer_init(nn.Linear(obs_dim, 128)), nn.Tanh(),
            layer_init(nn.Linear(128, 128)), nn.Tanh(),
            layer_init(nn.Linear(128, n_actions), std=0.01),
        )

    def get_value(self, x):
        return self.critic(x)

    def get_action_and_value(self, x, action=None):
        logits = self.actor(x)
        probs = Categorical(logits=logits)
        if action is None:
            action = probs.sample()
        return action, probs.log_prob(action), probs.entropy(), self.critic(x)


def main() -> float:
    args = parse_args()
    args.batch_size = args.num_envs * args.num_steps
    args.minibatch_size = args.batch_size // args.num_minibatches
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = torch.device("cpu")  # CPU-only image

    envs = envpool.make(args.env_id, env_type="gymnasium", num_envs=args.num_envs, seed=args.seed)
    n_actions = int(envs.action_space.n)
    obs0, _ = envs.reset()
    obs_dim = encode(obs0).shape[1]

    agent = Agent(obs_dim, n_actions).to(device)
    optimizer = optim.Adam(agent.parameters(), lr=args.learning_rate, eps=1e-5)

    obs = torch.zeros((args.num_steps, args.num_envs, obs_dim), device=device)
    actions = torch.zeros((args.num_steps, args.num_envs), device=device)
    logprobs = torch.zeros((args.num_steps, args.num_envs), device=device)
    rewards = torch.zeros((args.num_steps, args.num_envs), device=device)
    dones = torch.zeros((args.num_steps, args.num_envs), device=device)
    values = torch.zeros((args.num_steps, args.num_envs), device=device)

    global_step = 0
    start = time.time()
    next_obs = torch.tensor(encode(obs0), device=device)
    next_done = torch.zeros(args.num_envs, device=device)
    ep_ret = np.zeros(args.num_envs, dtype=np.float32)
    ret_window: deque[float] = deque(maxlen=100)
    num_updates = max(1, args.total_timesteps // args.batch_size)

    for update in range(1, num_updates + 1):
        for step in range(args.num_steps):
            global_step += args.num_envs
            obs[step] = next_obs
            dones[step] = next_done
            with torch.no_grad():
                action, logprob, _, value = agent.get_action_and_value(next_obs)
            values[step] = value.flatten()
            actions[step] = action
            logprobs[step] = logprob

            nobs, reward, terminated, truncated, _ = envs.step(action.cpu().numpy().astype(np.int32))
            done = np.logical_or(terminated, truncated)
            ep_ret += reward
            for i in np.nonzero(done)[0]:
                ret_window.append(float(ep_ret[i]))
                ep_ret[i] = 0.0
            rewards[step] = torch.tensor(reward, device=device).float()
            next_obs = torch.tensor(encode(nobs), device=device)
            next_done = torch.tensor(done, device=device).float()

        # GAE
        with torch.no_grad():
            next_value = agent.get_value(next_obs).reshape(1, -1)
            advantages = torch.zeros_like(rewards, device=device)
            lastgaelam = 0
            for t in reversed(range(args.num_steps)):
                if t == args.num_steps - 1:
                    nextnonterminal = 1.0 - next_done
                    nextvalues = next_value
                else:
                    nextnonterminal = 1.0 - dones[t + 1]
                    nextvalues = values[t + 1]
                delta = rewards[t] + args.gamma * nextvalues * nextnonterminal - values[t]
                advantages[t] = lastgaelam = delta + args.gamma * args.gae_lambda * nextnonterminal * lastgaelam
            returns = advantages + values

        b_obs = obs.reshape(-1, obs_dim)
        b_logprobs = logprobs.reshape(-1)
        b_actions = actions.reshape(-1)
        b_advantages = advantages.reshape(-1)
        b_returns = returns.reshape(-1)
        b_values = values.reshape(-1)

        b_inds = np.arange(args.batch_size)
        for _ in range(args.update_epochs):
            np.random.shuffle(b_inds)
            for s in range(0, args.batch_size, args.minibatch_size):
                mb = b_inds[s:s + args.minibatch_size]
                _, newlogprob, entropy, newvalue = agent.get_action_and_value(b_obs[mb], b_actions[mb].long())
                logratio = newlogprob - b_logprobs[mb]
                ratio = logratio.exp()
                mb_adv = b_advantages[mb]
                mb_adv = (mb_adv - mb_adv.mean()) / (mb_adv.std() + 1e-8)
                pg_loss = torch.max(
                    -mb_adv * ratio,
                    -mb_adv * torch.clamp(ratio, 1 - args.clip_coef, 1 + args.clip_coef),
                ).mean()
                v_loss = 0.5 * ((newvalue.view(-1) - b_returns[mb]) ** 2).mean()
                entropy_loss = entropy.mean()
                loss = pg_loss - args.ent_coef * entropy_loss + args.vf_coef * v_loss
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(agent.parameters(), args.max_grad_norm)
                optimizer.step()

        mean_ret = float(np.mean(ret_window)) if ret_window else 0.0
        sps = int(global_step / (time.time() - start))
        print(f"step={global_step} mean_return(last{len(ret_window)})={mean_ret:.3f} SPS={sps}", flush=True)

    final = float(np.mean(ret_window)) if ret_window else 0.0
    print(f"FINAL mean_return_at_{args.total_timesteps}_steps = {final:.4f}", flush=True)
    return final


if __name__ == "__main__":
    main()

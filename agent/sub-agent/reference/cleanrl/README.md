# CleanRL reference implementations

> **Background reading only — you do NOT copy or adapt these.** Sub-agents run
> experiments via the prebaked `scripts/train_ppo.py` (knob overrides), per
> `CLAUDE.md`. These single-file PPO implementations are here to *understand* how
> the training works — not to fork.

Single-file PPO references vendored from [CleanRL](https://github.com/vwxyzjn/cleanrl)
(`cleanrl/` on `master`).

| File | Read it to understand |
|------|-----------------------|
| `ppo_minigrid_envpool.py` | **PPO on MiniGrid via envpool** — the clearest single-file read for the envpool dict-obs encode + episode-return tracking that `scripts/train_ppo.py` does internally. |
| `ppo.py` | The discrete-action PPO core (on gym `SyncVectorEnv`). |
| `ppo_atari_envpool.py` | The generic envpool `make()` / step pattern (with an Atari CNN). |
| `ppo_continuous_action.py` | Continuous-action PPO (the MuJoCo shape). |

## Environments in this container

`envpool==1.2.5` provides, vectorized in C++:

- **MiniGrid** — `MiniGrid-DoorKey-8x8-v0`, `MiniGrid-Empty-*`, `MiniGrid-FourRooms-v0`,
  `BabyAI-*`, etc. Obs is a dict; flatten/encode it before the policy net.
- **MuJoCo** — `Ant-v4`, `HalfCheetah-v4`, `Hopper-v4`, `Humanoid-v4`, `Walker2d-v4`, ...
- Atari, classic control, Box2D, dm_control, ToyText.

```python
import envpool
envs = envpool.make("MiniGrid-DoorKey-8x8-v0", env_type="gymnasium", num_envs=64)
```

`torch` is CPU-only in this image (no CUDA) — keep nets small and step counts
within `plan.budget_steps`.

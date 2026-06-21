# CleanRL reference implementations

Single-file PPO references vendored from [CleanRL](https://github.com/vwxyzjn/cleanrl)
(`cleanrl/` on `master`). They are **reference code to read and adapt**, not a
library to import. Copy the closest one into your working dir and modify it for
your assigned idea — do not edit these originals.

| File | Use it for |
|------|-----------|
| `ppo.py` | Discrete-action PPO (gym vector envs). Closest base for **MiniGrid** tasks (Discrete action space). |
| `ppo_atari_envpool.py` | PPO wired to **envpool** (vectorized, the fast path). Copy its envpool `make()` / step loop when training on envpool envs. |
| `ppo_continuous_action.py` | Continuous-action PPO. Base for **MuJoCo** tasks (Ant, HalfCheetah, Hopper, Humanoid, Walker2d, ...). |

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

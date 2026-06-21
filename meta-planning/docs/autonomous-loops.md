# Autonomous Loops — v1.5

Let a research session run **many rounds on its own** toward a goal, instead of
one plan→dispatch→synthesize→exit. Built on the existing `chat_id`; no new chat.

## The model: runner spawns each round

Each round is a **fresh main-agent execution**. The agent does ONE round (plan →
dispatch → synthesize → graphs), reports its result, and exits. The **runner** then
applies the stop policy and either spawns the next round or marks the loop terminal.

Why not loop inside one process? Because the value of "autonomous" is a *hard*
keep-going guarantee. A single `claude -p` could loop itself, but "keep going"
would then be the model's choice (soft). Letting the runner own continuation makes
it deterministic, survives per-round crashes/timeouts, and isn't bounded by one
execution's wall-clock.

Division of labor:
- **Agent** does one round and reports facts (best metric, plan) — it never decides
  the loop is over.
- **Runner** owns the loop's terminal decision via the stop policy.

Carried over to a later v2: durable cross-session memory (the Findings Store).
Here, each round re-hydrates from the loop record via bootstrap.

## Data model

- `Session.mode = "autonomous"` (field already exists, `infra/schemas.py:52`).
  Set at `POST /sessions` with `max_rounds`.
- New **`loop:{sid}`** record (RedisJSON):

  ```
  { session_id, status, max_rounds, goal_metric, plateau_k, stop_requested,
    current_job_id, stop_reason, rounds: [ RoundRecord, ... ], created_at, updated_at }
  ```
- **RoundRecord**: `{ round_index, job_id, plan_id, best_metric, summary, ended_at }`.
- **Jobs are unchanged** (`JobStatus` untouched). A round's agent/sub-agent jobs are
  still `done`/`failed`. The loop is a new layer *above* jobs with its OWN terminal
  states — so a round agent exiting is just a round boundary, not the loop's end.

### Loop terminal states

| status | meaning |
|---|---|
| `running` | non-terminal — mid-round or between rounds |
| `completed` | stop policy satisfied (goal met, `max_rounds`, or plateau) |
| `stopped` | user halted |
| `budget_exhausted` | the atomic session budget hit zero |
| `failed` | unrecoverable error |

## One round (what the agent does)

```
agent boots → GET /internal/bootstrap   # goal + loop state (round N, prior bests)
  research skill   → plan                # deepen or escalate, given prior rounds
  dispatch + wait  → results
  synthesize       → best_metric + Plotly graphs
  report_round.py  → POST /internal/loop/round   # report facts, BEFORE exiting
  EXIT                                   # one round only — never loop in-process
```

## What spawns the next round (the runner)

```
round agent exits → reconcile _finalize_done (depth 0)
  → _advance_loop: read loop:{sid} + budget
     count this round (backstop if the agent didn't report it)
     stop policy:  continue → create next depth-0 job, re-point session root,
                              enqueue (session_loop spawns it), emit round_started
                   stop     → set loop:{sid} terminal + reason, emit loop_stopped
```

The runner owns continuation, so "keep going" is a hard guarantee, not the model's
choice. Between rounds the new queued job keeps the session non-terminal; cleanup
also explicitly skips a session whose loop is still `running` (no premature token
revoke).

### Loop terminal states

| status | meaning |
|---|---|
| `running` | non-terminal — mid-round or between rounds |
| `completed` | stop policy satisfied (goal met, `max_rounds`, or plateau) |
| `stopped` | user halted |
| `budget_exhausted` | the atomic session budget hit zero |
| `failed` | unrecoverable error |

## Stop policy = the terminal definition (`infra/loop_policy.py`)

A pure function `decide(loop, budget)` the runner calls at each round boundary.
Stop when **any** (order = priority):

- `stop_requested` is set          → `stopped`
- session budget == 0              → `budget_exhausted`
- `len(rounds) >= max_rounds`      → `completed` (hard backstop — never runs forever)
- latest round reached `goal_metric` → `completed`
- **plateau**: no new best over the last `plateau_k` rounds → `completed`

Runner-side and pure, so it's deterministic, fully unit-tested, and outside the
model's whim. A round that exits without reporting is still *counted* (a backstop
stub round), so `max_rounds` always bites even if the agent crashes.

## User stop

`POST /sessions/{id}/stop` → sets `loop:{sid}.stop_requested = true`. The runner
reads it at the **next round boundary** and finalizes the loop as `stopped` instead
of spawning another round.

## Frontend (backend-first)

Loop events ride the existing per-session SSE stream as `status`/`summary` events
with a `phase` payload (no enum migration): `round_started`, `round_synthesized`
(metric), `loop_stopped` (reason). The "Autonomous Loop" section renders those + the
`loop:{sid}` doc (exposed via `GET /sessions/{id}`). UI polish is later.

## Files (implemented)

- `infra/schemas.py` — `LoopStatus`, `RoundRecord`, `Loop`.
- `infra/loop_policy.py` — the pure stop policy `decide()`.
- `infra/store.py` — `create_loop` / `get_loop` / `append_round` /
  `set_loop_status` / `request_loop_stop` / `set_loop_current_job` (key `loop:{sid}`).
- `runner/loops.py` — `_advance_loop` (spawn next round or terminate) + cleanup guard.
- `runner/internal_api.py` — bootstrap returns loop state; `POST /internal/loop/round`.
- `orchestrator/api.py` — `POST /sessions` takes `mode`/`max_rounds`/`goal_metric`;
  `POST /sessions/{id}/stop`.
- `agent/main-agent/` — `scripts/report_round.py`; `CLAUDE.md` + launch prompt
  (one round, then report + exit).

## Explicitly NOT in v1.5

Cross-session memory / the durable Findings Store, richer escalation than
deepen-vs-plateau, and per-round artifact reuse — those build on
[`competence-plan.md`](./competence-plan.md).

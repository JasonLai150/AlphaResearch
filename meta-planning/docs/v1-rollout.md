# v1 end-to-end rollout — two PRs to a live research run

Status anchor (2026-06-21): infra is **deployed and the backbone is proven on real
cloud**. `POST /sessions` → Redis → `sessions:queue` → runner leader loop → a live
Cloud Run Job execution → state back in Redis, all verified. Modal (`sub_agent` +
`run_job`) deployed; Cloud Run service `alpha-api` live at
`https://alpha-api-ziyr677nma-uc.a.run.app`; GCP bootstrap done.

**What's missing for an end-to-end run** are two code gaps (no more infra):
1. Agents spawn but **don't run** — interactive `claude` entrypoint in a batch Job
   with no TTY, and the goal is never passed into the container. → **PR1**.
2. Sub-agent results/artifacts **can't flow back** — the runner reads them from a
   Modal Volume it can't mount from Cloud Run (broken **both** directions: dispatch
   out *and* result back). → **PR2**.

v1 ships on the **synthetic** experiment stub (proves the pipeline). Real PPO+MiniGrid
is a later PR.

---

## The goal's lifecycle (why PR1 is shaped the way it is)

There are two distinct "goals". Don't conflate them:

| | What | Made by | Consumed by |
|---|---|---|---|
| **user goal** (raw text) | "improve sample efficiency on DoorKey" | the **user** (`POST /sessions`) | the **main agent** as its seed |
| **`ResearchPlan`** (structured) | `{env_id, reward_fn_spec, base_hparams, target_metric, budget_steps, ideas[]}` | the **main agent** (derives via `research` skill) | the **sub-agents** (one idea each) |

The raw user goal already lives in Redis (`session.goal` + `root_job.params.goal`);
it just never reaches the container.

**Future direction (designed for, not built yet):** the raw goal will be *derived
from a conversation* between user and main agent (the "chatbot for research" /
`memory-chatbot.md` end-state). That tips PR1's key decision toward a **bootstrap
endpoint** over env-injection — a set-once env var can't carry a growing
conversation, but a `GET /internal/bootstrap` extends cleanly to return the
conversation + `mode:"conversational"` later. The main agent's existing "ask 2-4
clarifying questions" step *is* the seed of that conversation; PR1 suppresses it
behind a `mode` flag, the conversational PR flips it on.

```
oneshot (PR1):  goal ──► bootstrap ──► main agent ──► ResearchPlan ──► dispatch
future:         user ⇄ main agent (clarify/refine, N turns) ──► converged plan ──► dispatch
```

---

## PR1 — Headless agent invocation  (`feat/headless-agents`)

**Goal:** a spawned main-agent Job and sub-agent Modal fn actually *run* Claude Code
non-interactively, driven by the goal, producing transcript + dispatch (main) and a
result (sub).

**Changes**
- [ ] `infra/schemas.py` — add `Session.mode: str = "oneshot"`.
- [ ] `infra/store.py` — `create_session` accepts/stores `mode` (default `"oneshot"`).
- [ ] `runner/internal_api.py` — **`GET /internal/bootstrap`**: token→session, returns
      `{session_id, root_job_id, goal, depth, mode}`. (Hidden from OpenAPI, like the rest.)
- [ ] `agent/main-agent/entrypoint.sh` (new) — fetch `/internal/bootstrap`, build a
      bootstrap prompt embedding the goal, exec
      `claude -p "<prompt>" --model "$ALPHA_MODEL" --output-format stream-json
      --dangerously-skip-permissions`. Set `ALPHA_NONINTERACTIVE=1`.
- [ ] `agent/sub-agent/entrypoint.sh` (new) — prompt: read CLAUDE.md +
      `.dispatched/$ALPHA_JOB_ID.json`, run the idea, write `result.json`; same
      `claude -p` exec.
- [ ] `deploy/{main-agent,sub-agent}.Dockerfile` — `ENTRYPOINT` → the wrapper.
- [ ] `infra/modal_app.py` `sub_agent()` — call the wrapper / `claude -p` + prompt
      (Modal overrides the entrypoint, so it must change here too).
- [ ] `agent/main-agent/CLAUDE.md` — gate the "ask 2-4 questions" step on
      interactivity (`ALPHA_NONINTERACTIVE`): batch run states defaults & proceeds.
- [ ] `runner/cloud_run_client.py` — keep injecting ids + token; **no goal env** (the
      agent fetches it). Add `ALPHA_MODEL` to the override.

**Acceptance**
- Manual Job run with a session's token → `/sessions/{id}/full` shows non-empty
  `transcript` **and** ≥1 dispatched child.
- Manual sub-agent run reads a dispatch record and writes `result.json`; Stop hook fires.

**Tests:** unit-test bootstrap (auth, token→session, payload) + the wrapper prompt
build; smoke: create session, poll `/full` until transcript non-empty + child appears.
**Deploy:** rebuild main-agent + sub-agent images; `gcloud run jobs update` + `modal deploy`.
**Risks:** hooks firing under `-p`; one-shot dispatch behavior; cold start; 4h Job cap.

---

## PR2 — Two-way push (Option 2), remove the Modal Volume  (`feat/two-way-push`, off main after PR1)

**Goal:** dispatch records go out as a Modal arg; results+artifacts come back over
HTTP+GCS. No shared filesystem anywhere (matches the main-agent's design).

**Outbound (dispatch → sub-agent)**
- [ ] `infra/modal_app.py` `sub_agent()` — accept `dispatch_record: str`, write to
      `/workspace/.dispatched/<jid>.json` on boot; drop the volume mount.
- [ ] `runner/modal_client.py` `spawn_sub_agent()` — pass `json.dumps(record)`; remove
      vol create/commit/mount.
- [ ] `runner/loops.py` `_consume_dispatches_once` — build record, pass to spawn (no
      disk write).

**Inbound (result+artifacts → runner → Redis/GCS)**
- [ ] `infra/schemas.py` — `ResultIn` body: `status/summary/metrics/artifacts[]` +
      optional `patch`, `base_ref` (future-git seam).
- [ ] `runner/internal_api.py` — **`POST /internal/result`**: token→session auth,
      validate job ownership+depth, `write_run` + `put_artifact` per artifact
      (base64, size-cap ~10MB, skip+warn over cap) + `set_job_status` + emit summary;
      **idempotent**.
- [ ] `agent/sub-agent/.claude/hooks/finalize.py` — read `result.json` +
      `artifacts/<jid>/*`, base64, POST `/internal/result`; drop the volume write.
- [ ] `runner/loops.py` `_finalize_done` depth≥1 — read `RunResult` via
      `store.get_run`; Modal-call-done-but-no-result after a grace window → failed.
      Remove `reload_volume`/sentinel/`results_for` reads.
- [ ] `runner/modal_client.py` — retire `write_dispatch_record`/`reload_volume`/
      `results_for`/`result_done_sentinel`/`delete_session_volume` to no-ops.
- [ ] tests — `/internal/result` (auth, idempotency, size-cap, depth); reconcile reads
      Redis; dispatch-arg pass; delete volume tests.

**Acceptance:** full e2e — session → main dispatches 2 subs → subs run (PR1) → each
POSTs result + a plot → `/full` shows `runs` with metrics + `artifacts` (GCS https
URLs) → main synthesizes. Modal Volume used nowhere. Idempotent re-POST; oversized
artifact handled; sub that dies before posting → failed.
**Deploy:** rebuild both images; `gcloud run` + `modal deploy`.

---

## Ordering
Prep (deploy hardening, merged) → **PR1** → **PR2**. PR2 *code* can be written in
parallel but its e2e check needs PR1 (subs must run to post results). Budget ~1 flaky
deploy each (retries are in the Dockerfiles now).

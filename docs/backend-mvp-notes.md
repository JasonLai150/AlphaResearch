# Backend MVP — implementation notes, assumptions & known gaps

This documents decisions made implementing `docs/superpowers/plans/2026-06-20-backend-mvp.md`
plus the SEV-1/SEV-2 fix list, and the load-bearing assumptions a reviewer/operator must know.

## Architecture decision: Cloud Run Job main-agent is authoritative

The plan was internally inconsistent: the Task bodies (1–9) put the main-agent on Modal with a
`volume_watch_loop`, but the "Architecture revision" section and the **entire SEV fix list** assume
the main-agent runs as a **Cloud Run Job** and dispatch flows via `POST /internal/dispatch`. We built
the Cloud Run revision as authoritative:
- `runner/cloud_run_client.py` spawns/polls the main-agent Job; sub-agents stay on Modal.
- **There is no `volume_watch_loop`.** Child jobs are registered via the internal API, not by scanning
  a shared volume. Several plan-body unit tests were adapted to this arch.

## Final adversarial review — outcome

Two adversarial review passes ran (midpoint + final). **Fixed and committed** from the final
pass: the critical `parent_job_id="root"` default → now `$ALPHA_JOB_ID` (dispatch would have
404'd in prod); `_finalize_done` now honors a sub-agent's self-reported `status:"failed"` instead
of masking it as done; `gcs_uploader` now uses the shared SA-key credential path (was bare ADC →
403 on Cloud Run); atomic spawn-commit (`store.mark_job_running`, no queued-with-live-sandbox
window); graceful main-agent success no longer cancels running children; terminal-session cleanup
has a grace window before revoking the token; `set_job_status` guards job existence (no real-Redis
index drift); async `delete_session_volume`; doc contradictions fixed. **The one finding left as a
design decision is the volume bridge below** (the #1/#2/#3 criticals all point at it).

## ⚠️ KNOWN GAP (must address before real cloud runs): runner ↔ Modal volume access

The reconcile loop reads a finished sub-agent's `result.json` / `.done` sentinel / artifacts from a
**local filesystem path** (`runner/modal_client.py::dispatch_dir(sid)` = `$ALPHA_VOLUME_ROOT/<sid>/.dispatched`),
and `reload_volume()` calls `modal.Volume.reload()`. This is the plan's design and it works in tests
(local tmp volumes) — but **Cloud Run cannot natively mount a Modal Volume**, so on the real
orchestrator that local path will be empty and sub-agent results won't propagate.

Pick one before production:
1. **Read via the Modal SDK** (recommended): replace `reload_volume()` with a hydrate step that uses
   `modal.Volume.from_name(...).iterdir()/read_file()` (or `batch_download`) to pull the session's
   `.dispatched/` tree into `dispatch_dir(sid)` before reconcile reads it. Integration-only; verify
   against the installed `modal` version. The reconcile state machine already handles "sentinel not
   yet present → wait / eventually fail", so a best-effort hydrate is safe.
2. **Have the sub-agent push its result** to a new `/internal/result` endpoint (and GCS-upload its own
   artifacts), removing the runner↔volume dependency entirely. Larger change.

Everything else (Redis state, GCS, Cloud Run Job spawn/poll, internal API, tokens, leader lease) does
not depend on this and works as-is.

## SEV fixes — where each lives

| SEV | Fix | Location |
|----|----|----|
| 1 | spawn gating + xdel-after-success | `runner/loops.py::_consume_sessions_once/_consume_dispatches_once` |
| 2 | runner leader lease (Lua CAS acquire/refresh/release) | `infra/store.py`, `runner/loops.py::leadership_loop` |
| 3 | field-level status write + pure-function status index | `infra/store.py::set_job_status` |
| 4 | per-session ephemeral token (mint at spawn, inject per-exec, resolve→session) | `infra/store.py`, `cloud_run_client.py`, `modal_client.py`, `internal_api.py` |
| 5 | `/internal/*` hidden from OpenAPI | `internal_api.py` (`include_in_schema=False`) + `api.py` (`_public_openapi`) |
| 6 | terminal-session volume + token cleanup (once via SET NX) | `runner/loops.py::_cleanup_terminal_sessions` |
| 7 | sub-agent atomic `result.json` + `.done` sentinel; reconcile requires sentinel, bad JSON→failed | `agent/sub-agent/.claude/hooks/finalize.py`, `runner/loops.py::_finalize_done` |
| 8 | cancel non-terminal children when a parent goes terminal | `runner/loops.py::_cancel_orphans_if_terminal` |
| 9 | refuse `sandbox_id=None` (assert `op.metadata.name`) | `runner/cloud_run_client.py::spawn_main_agent_job` |
| 10 | deterministic artifact ids | `infra/store.py::deterministic_artifact_id` (used by `put_artifact` + `gcs_uploader`) |
| 11 | `modal_call_id` dropped from schema + dispatch.py | `infra/schemas.py`, `infra/dispatch.py` |
| 12 | reconcile re-fetches each job before acting | `runner/loops.py::_reconcile_once` |
| 13 | Redis ping on startup + bounded retry in agent push | `api.py` lifespan, `agent/*/.claude/hooks/_push.py` |

## Smaller assumptions worth a second look

- **SEV-4 token transport to sub-agents:** the per-session token is passed to the `sub_agent` Modal
  function as a call argument (`internal_token=`). It is session-scoped + 24h TTL + revoked on cleanup.
  For defense-in-depth (Modal call args can appear in dashboards/logs), consider switching to a
  per-call `modal.Secret.from_dict({...})` injected via `with_options(secrets=[...])`.
- **Leader lease + `--max-instances=1`:** the deploy pins the service to 1 instance, but the lease
  (SEV-2) is what makes a rolling-deploy overlap safe — it is now safe to raise `--max-instances`.
- **Horizontal scale follow-up:** queue draining uses non-blocking `XREAD` + `XDEL` under a single
  leader. For multi-consumer scale, migrate to `XREADGROUP`/`XACK` (the `ack_stream` no-op is a seam).
- **`store.read_state` / `get_session`:** the session doc carries a `root_job_id` field not on the
  `Session` model; pydantic ignores it on validate (no `extra="forbid"`), so reads are unaffected.
- **`modal_call_id` migration:** old Redis docs may still carry `$.modal_call_id`; it's ignored on
  read (extra field). A one-shot `SCAN job:* → JSON.DEL $.modal_call_id` sweep can clean it if desired.

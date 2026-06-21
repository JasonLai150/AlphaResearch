# PR2 handoff — two-way push (remove the Modal Volume)

Branch: **`feat/two-way-push`** (stacked on `feat/headless-agents` = PR1). Pushed.
Read `v1-rollout.md` for the overall two-PR plan; this doc is the live PR2 state.

## TL;DR
PR1 (headless agents) is **verified live**: a session spawns the main agent, it fetches
its goal from `GET /internal/bootstrap`, runs `claude -p`, and dispatches sub-agents.
PR2 removes the Modal Volume so dispatch records go *out* as a Modal call arg and
results/artifacts come *back* over HTTP+GCS. PR2 code + 77 tests are green and deployed.
**Last open item: confirm the full live round-trip** (sub-agents posting real results).

## What PR2 changed (all committed)
- **Outbound**: dispatch record rides as a Modal call arg. `runner/modal_client.py
  spawn_sub_agent(job_id, session_id, record)` passes `dispatch_record=json.dumps(record)`;
  `infra/modal_app.py sub_agent()` writes it to `/workspace/.dispatched/<jid>.json` on boot
  (chowned to the `agent` user). No volume mounted.
- **Inbound**: `POST /internal/result` (`runner/internal_api.py`) — token→session auth,
  idempotent, base64 artifacts → `store.put_artifact` (GCS), 10MB/artifact cap, flips job
  status, emits a summary event. The sub-agent Stop hook
  (`agent/sub-agent/.claude/hooks/finalize.py`) reads `result.json` + `artifacts/<jid>/*`,
  base64s them, and POSTs.
- **Reconcile** (`runner/loops.py _finalize_done`): depth≥1 reads the pushed `RunResult`
  from Redis (`store.get_run`); Modal-call-done-but-no-result → failed. All volume plumbing
  retired.
- **Schema**: `RunResult` gained optional `patch` + `base_ref` (future-git seam, unused).
- **Tests**: rewrote `test_modal_client`, `test_runner_loops`, `test_hooks`, `test_e2e_smoke`
  for the push model + new `/internal/result` tests. **77 pass, ruff clean.**

## Bugs found + fixed during live verification (each was a separate commit)
1. **`claude` refuses `--dangerously-skip-permissions` as root** → run agents as a non-root
   `agent` user. Main-agent image sets `USER agent`; the sub-agent drops to `agent` via
   `subprocess(user="agent")` in `sub_agent()`.
2. **Runner had no Modal creds** (Cloud Run has no `~/.modal.toml`) → every sub-agent spawn
   hit `AuthError`, stuck `queued`. Added GCP secrets `modal-token-{id,secret}` + injected
   `MODAL_TOKEN_{ID,SECRET}` into the service (`deploy_cloudrun.sh` persists this).
3. **Modal ran the inherited Dockerfile `ENTRYPOINT`** (`from_dockerfile` images) → launch.py
   fired at boot with no args → `[launch] missing ALPHA_JOB_ID`, exit 1, every sub-agent.
   Fixed with `.entrypoint([])` on the Modal image + removed `USER agent` from the sub-agent
   image (Modal's harness needs root).

## Live status (as of handoff)
- Latest test session `s_420f106096e5` on `https://alpha-api-ziyr677nma-uc.a.run.app`:
  main agent dispatched **3 sub-agents**; they ran for minutes (NOT fast-failing → they
  found their dispatch records), but had not posted results yet when this doc was written.
- A `claude -p` sub-agent does real work (cold start + reasoning + experiment), so the
  round-trip takes several minutes. Watch with:
  ```bash
  URL=https://alpha-api-ziyr677nma-uc.a.run.app
  curl -s "$URL/sessions/<sid>/full" | python3 -m json.tool   # look at runs[] + artifacts[]
  ```

## Open items / next steps for whoever picks this up
1. **Confirm the round-trip**: a fresh session should end with `runs[]` carrying real
   `metrics` and `artifacts[]` with GCS `https://…` URLs, and the main agent synthesizing.
   If sub-agents post `status:"failed" "dispatch record absent"`, the outbound write in
   `sub_agent()` regressed — check `/workspace/.dispatched/<jid>.json` exists in the
   container (debug via `modal app logs alpharesearch`).
2. **Cosmetic: silence `sitecustomize` PermissionError** — the `agent` subprocess can't read
   Modal's root-owned `/pkg/sitecustomize.py` (non-fatal, Python continues). Fix: in
   `sub_agent()` drop `PYTHONPATH` from the subprocess `env` (`env.pop("PYTHONPATH", None)`)
   — launch.py is stdlib-only and claude is node, so neither needs Modal's `/pkg`.
3. **`/healthz` returns a Google 404** while every real route works — minor, unexplained;
   worth a look before demo.
4. **Old job noise**: the Modal dashboard mixes sub-agents from earlier (PR1-era) sessions;
   filter by the *current* session's job ids (from `/sessions/<sid>/full`) when debugging.

## Deploy (after any change)
```bash
bash scripts/deploy_cloudrun.sh        # api (runner) + main-agent images  (retry on flaky net)
uv run modal deploy infra/modal_app.py # sub-agent + run_job
```
Images: PR2 changed the **api** (runner) and **sub-agent** images. Cold-start + congested
networks mean budget ~1 retry per deploy (retries are baked into the Dockerfiles).

## Commits on this branch (newest first)
- `fix(sub-agent): clear inherited ENTRYPOINT on Modal; don't set USER in image`
- `feat(two-way-push): remove the Modal Volume; results+dispatch over HTTP (PR2)`
- (below this point are PR1 + prep: Modal creds, non-root, bootstrap+launchers, deploy hardening)

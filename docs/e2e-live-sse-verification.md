# e2e live-SSE verification (2026-06-21)

Bring-up + verification that the **web frontend connects to the backend and renders live
SSE chat streams end-to-end** — locally first, then against the deployed Cloud Run backend.
This is a verification record (no application source changed); it captures what was proven
and the remaining gaps for a full deployed demo.

## UX contract (confirmed)
- **Chat is with the lead agent only.** The composer posts to `POST /sessions/{id}/messages`
  (placeholder "Reply to the lead agent…"). Sub-agents are never a reply target.
- **Sub-agents stream one-way** over SSE into the **tree view** (agent graph + sub-agent
  cards + reward sparklines + artifacts) and surface in the **chat feed** as the lead's
  narration ("Dispatched sub-agent X — …").

## Local stack — VERIFIED ✅
- **How:** `bash scripts/dev_api_local.sh` (redis-stack + API on `:8080`, `ALPHA_LOCAL_SIM=true`,
  runner off, artifacts → disk) + frontend on `:3000` with `web/.env.local` →
  `http://localhost:8080`.
- **Wiring:** full chain over localhost all 200 — `POST /sessions` → `GET /sessions/{id}/full`
  → **`GET /sessions/{id}/stream`** (SSE) → artifact (`reward.svg`) served from disk. CORS
  preflight passes; keyless `demo` auth.
- **Live SSE (timestamped capture):** every event type arrived incrementally over ~7.5s —
  `log` → `status` → `token` deltas (word-by-word lead narration) → `spawn` ×3 sub-agents →
  depth-2 experiments → `metric` ×N (reward curves climbing) → `summary` + `artifact` →
  final `summary`, plus `: ping` keepalive. SSE wire format `id:`/`event:`/`data:` with Redis
  stream entry-IDs (so `Last-Event-ID` resume works).
- **UI:** 3-pane console renders it live — lead-only transcript (center), agent graph +
  sub-agent cards + sparklines + artifact (right rail).

## Deployed (Cloud Run `alpha-api`) — backbone VERIFIED ✅; full UI demo needs a redeploy
- **Reachability:** `/health` 200; CORS allows `http://localhost:3000` (origin + credentials +
  `authorization,content-type`). Auth is keyless (no Clerk enforced).
- **Reads healthy after the 2026-06-21 GCP/Redis fix:** `GET /sessions/{id}` returns
  `200 {"session":null,...}` (previously **500** — Redis Cloud was unreachable from Cloud Run).
- **Live SSE + real runner proven:** a real session (`POST /sessions`) streamed a
  `status: running` event at **+1.4s** carrying a real Cloud Run Job execution
  (`jobs/alpha-main-agent/executions/…`), and the SSE connection stayed live via keepalive
  pings while the Job ran. End-to-end backbone confirmed: **POST → runner → real Cloud Run Job
  → status in Redis → SSE to client.**
- **Two gaps for a full frontend↔deployed demo:**
  1. **Stale build.** Deployed openapi exposes only `/health`, `POST /sessions`,
     `GET /sessions/{id}`, `/full`, `/stream`, `POST /sessions/{id}/stop` — it is **missing
     `GET /sessions`** (sidebar list → 405) and **`POST /sessions/{id}/messages`**
     (follow-up chat → 404/405). Initial goal + live stream work; sidebar list and
     follow-up chat do not. → redeploy current build (`scripts/deploy_cloudrun.sh`).
  2. **Real vs scripted stream.** Deployed runs the real runner, not `local_sim`, so the rich
     token/metric/dispatch stream depends on the real agent round-trip (M3/M4/M5), not the
     synthetic script.

## Reproduce
- **Local:** `bash scripts/dev_api_local.sh`, then `cd web && npm run dev`; open
  `http://localhost:3000`.
- **Deployed SSE smoke:** `POST /sessions` `{user_id, goal}` then read
  `GET /sessions/{id}/stream` (expect a `status` event with the Cloud Run execution id).

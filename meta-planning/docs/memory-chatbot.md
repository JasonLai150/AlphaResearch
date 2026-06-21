# Memory & Research-Chatbot Design

How AlphaResearch becomes a **conversational research chatbot with durable memory**,
using the **Redis Agent Memory Server (AMS)**. Additive to the existing stack — it does
**not** replace the orchestration Redis (jobs/runs/events), the SSE stream, or GCS.

Refs: [AMS](https://github.com/redis/agent-memory-server) ·
[MCP](https://redis.github.io/agent-memory-server/mcp/) ·
[long-term memory](https://redis.github.io/agent-memory-server/long-term-memory/)

---

## 1. Goal
Turn the one-shot `goal → events` runner into a multi-turn chatbot that (a) remembers the
conversation, and (b) accumulates research findings across sessions so it gets smarter.

## 2. Why AMS
Two memory types map exactly onto the two gaps (`design.md` "long-horizon memory"):

| Gap today | AMS feature | Scope |
|---|---|---|
| No chat persistence | **Working memory** (session messages, auto-summarized) | per session |
| No agent memory | **Long-term memory** (semantic/keyword/hybrid search, lifecycle) | per user/project |
| Harness needs memory | **MCP server** (`memory_prompt`, `search_long_term_memory`, `create_long_term_memories`) | tool layer |

AMS runs on Redis (Search module) → same sponsor backplane. The main-agent is Claude Code,
which speaks MCP natively → memory is a config add, not custom plumbing.

## 3. Component responsibilities (what lives where)
```
┌ Conversation + memory (NEW) ─ Redis Agent Memory Server ───────────────┐
│  working memory  = session transcript (user+assistant turns)           │
│  long-term memory = validated findings, user prefs/constraints (vectors)│
└────────────────────────────────────────────────────────────────────────┘
┌ Orchestration state (UNCHANGED) ─ our Redis via infra/store ───────────┐
│  session / job / run / artifact (JSON), events Stream, budget, queue    │
└────────────────────────────────────────────────────────────────────────┘
GCS = artifact blobs (unchanged)        SSE = live transport (unchanged)
```
Rule of thumb: **AMS = what the agent says and remembers; our Redis = what the system is
doing.** Never duplicate orchestration state into AMS.

## 4. The conversational loop (per-turn, stateless agent)
The key shift: the main-agent is no longer one long-lived process per session. Each user
turn is a fresh main-agent invocation that **hydrates from AMS**:

```
user turn ─► API POST /sessions/{sid}/messages
   └─ append user turn to AMS working memory
   └─ enqueue a main-agent turn (sessions:queue) ─► runner launches the harness
        1. memory_prompt(session_id, user_id) → working memory + relevant long-term memory
        2. decide: plain chat reply  OR  launch/continue a research run (dispatch sub-agents)
        3. stream tokens/status via the events Stream → SSE → UI
        4. write the assistant turn back to AMS working memory
        5. (on a validated finding) create_long_term_memories
```
Memory lives in AMS, so the agent is stateless between turns — cleaner than holding a
Claude Code process open, and exactly AMS's intended pattern.

## 5. API changes (`orchestrator/api.py`)
- `POST /sessions` — create session (unchanged shape) **+ store the first user turn** in AMS,
  then enqueue (already enqueues `sessions:queue`).
- `POST /sessions/{sid}/messages` `{content}` — **NEW**: append user turn to AMS working
  memory, enqueue a main-agent turn. This is also what unblocks the harness's intended
  "probe the user with clarifying questions" step (currently no reply channel exists).
- `GET /sessions/{sid}/messages` — **NEW**: return the working-memory transcript (UI load /
  refresh). The events Stream stays for *live* deltas; this is the durable transcript.
- `GET /sessions` (per `user_id`) — later, for chat history list.
- SSE stream — unchanged.

## 6. Harness integration (Claude Code, MCP)
- Add the AMS MCP server to `agent/main-agent/.claude/settings.json` `mcpServers`.
- Update `agent/main-agent/CLAUDE.md` workflow: **start** each turn with `memory_prompt`
  (load working + relevant long-term memory); **end** by recording the turn and promoting
  durable findings via `create_long_term_memories`.
- `agent/sub-agent/` gets **no** memory access — sub-agents stay isolated; their findings
  flow up via `result.json` and the runner promotes them (§7).

## 7. Runner integration (who writes long-term memory)
The runner already bridges `result.json` → Redis. Extend it: on a result with
`validated: true`, also call AMS `create_long_term_memories` with the finding. Keeps the
agent↔agent "summaries-up" model; AMS is just the durable cross-session layer.

`result.json` → LongTermFinding mapping:
```
text       = summary + validation_reasoning
metrics    = { target_metric, delta_vs_baseline, n_seeds }
scaffold   = { env_id, target_metric, budget_steps }     # from the plan
topics/tags= [ user_id, plan.id, env_id, idea.diversity_tag ]
source     = { session_id, job_id }
```

## 8. Deployment
- AMS as a separate service (Docker → **Cloud Run**), backed by Redis with the Search module.
- **Recommend a dedicated memory Redis** (second Redis Cloud DB or index) — vector/search
  access patterns differ from our streams/JSON, and AMS owns its keyspace. Simpler option:
  same DB if it has Search enabled.
- AMS needs an LLM (via LiteLLM) for summarization/extraction — point at Anthropic (a cheap
  model is fine for extraction).
- New config/secrets: `ALPHA_AMS_URL`, AMS auth token. Add to `.env`, the Modal secret, and
  the main-agent harness env.

## 9. Open decisions
- **Same vs dedicated Redis for AMS** (recommend dedicated).
- **AMS extraction model** (cost vs quality).
- **Namespacing**: per `user_id`; no auth yet (defaults to `"user"`) — add auth before
  multi-user history is meaningful.
- **Promotion policy**: auto-promote `validated: true` findings only, or let the lead agent
  curate which findings become long-term memories.
- **Forgetting/compaction** config (AMS lifecycle defaults vs tuned).

## 10. Staged rollout
- **A — Chat persistence:** AMS up; working memory; `POST/GET /sessions/{sid}/messages`; UI
  loads transcript. → multi-turn chat that survives refresh + a reply channel for clarifying Qs.
- **B — Agent memory:** runner writes long-term findings; main-agent `search_long_term_memory`
  at planning time. → cross-session research memory.
- **C — Research chatbot:** the full chat⇄research loop — the agent decides when to launch a
  run, streams progress, folds results into memory, answers follow-ups grounded in past work.

## 11. Non-goals / boundaries
- AMS does not replace orchestration Redis, the events Stream, or GCS.
- Sub-agents remain memory-isolated.
- This doc is additive to `design.md`; it depends on the runner seam (`sessions:queue` +
  `.dispatched/` ⇄ Redis) being in place.

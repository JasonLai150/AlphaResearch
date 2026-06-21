# Agent Competence — Concept & Plan

How the main agent gets more competent along three axes: a sharper single-session
harness, continuity across a user's chats, and self-improvement over a long-horizon
goal. Companion to [`plan.md`](./plan.md); this doc is the *why* and the *order*.

## Thesis

Three problems, one root. The director (1) **drowns in and trusts** unverified
sub-agent output, (2) **forgets everything** between chats, and (3) if we add memory
naively, will **persist the wrong thing** (plans, narrative) and rot. The fix is one
discipline applied everywhere:

> **Persist verified facts, not plans. Regenerate plans fresh from facts each session.**

Plans are cheap LLM output and go stale; the expensive things (compute, checkpoints,
empirical numbers) already live as artifacts. Cache facts, not the reasoning over them.

## Current persistence (today — there is no ledger)

Nothing crosses sessions; everything is session-keyed and effectively discarded.
- `run:{jid}` (Redis) — a sub-agent's final RunResult `{status, summary, metrics}`. The
  closest thing to a "finding," but **no conditions-stamp, no effect size/variance/
  confidence, no verification**, and the reported `validated` flag is **dropped on write**
  (`store.write_run` keeps only status/summary/metrics/patch).
- `artifact:{aid}` (Redis metadata) + blob in **GCS** — plots/checkpoints/logs.
- `session:{sid}:events` (Redis Stream) — live telemetry, not durable history.
- Session-scoped, no per-user index, `mode="oneshot"`. The director synthesizes, exits,
  and the synthesis is lost.

The Findings Store is therefore net-new — it sits *beside* the per-session Redis state as
a durable, per-user, local-file store the skills/scripts own (see "Where the changes live").

## Invariants (load-bearing — every change respects these)

1. **Nothing enters the director's context or any store unverified.** A sub-agent's
   `validated`/metrics are claims, not truth, until the director recomputes the delta
   from raw numbers and confirms a matching artifact exists.
2. **Every persisted fact is conditions-stamped** (env hash, seed range, eval protocol)
   and **immutable** — corrected by `supersedes:<id>`, never edited or deleted. Staleness
   stays *visible* instead of silently misleading a future session.
3. **Read metrics-first.** Full result/artifact bodies enter context only on explicit,
   one-at-a-time request, and are capped at the source.
4. **Plans are ephemeral.** No plan tree is ever written to disk. Hierarchy, if any,
   lives over *findings* (a results/ancestry graph), never over plans.
5. **No self-referential memory.** The agent never logs facts about its own progress or
   planning quality — that is the Goodhart on-ramp.

## The unifying primitive

A **verification-gated, conditions-stamped, append-only Findings Store.** One mechanism
serves all three layers: it's the trust gate (L1), the cross-chat ledger (L2), and the
long-term fact base (L3). Build it once; everything else attaches to it.

```
sub-agent result ──▶ [verify: recompute delta, match artifact, outlier check]
                        │ pass                          │ fail
                        ▼                                ▼
              Findings Store (immutable,          scratch (session-local,
              conditions-stamped)                  never persists)
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                 ▼
   director         next session      long-horizon
   synthesis        regenerates       plan regen +
   (this chat)      plan from facts   dead-end avoidance
```

## Structure over the facts (the three requirements force these five)

The trunk stores facts. Three concrete asks — recall opinionated claims, pivot when
failing, trend long-running results — force a thin structure *over* the facts (never
over plans):

1. **Campaign anchor** `= (env_id, target_metric, budget_steps)` — the unit of
   cross-session comparability. Pivots happen *under* an anchor (same question, new
   approach) or *fork* it (new question). Trends only mean anything within one anchor.
2. **Two-level findings** — idea-level (one intervention's delta) + an **approach-class
   rollup** (best by e.g. `ppo-family` vs `grpo-family`). The per-session frozen scaffold
   gives within-session fairness; the anchor + rollup give cross-approach fairness — what
   makes "best PPO vs best GRPO" a fair fight even though their hparams differ.
3. **Retrieval + claim contract** — recall the relevant dense facts (by anchor /
   diversity_tag / recency / effect size); every opinionated claim cites finding IDs +
   effect size + confidence (n_seeds) + conditions. Falsifiable, auditable, auto-stale on
   `supersedes`. **Leverage lives in retrieval, not storage.**
4. **Escalation policy (deepen vs escalate)** — explore/exploit driven by trends. While
   marginal gain/cost stays above threshold and the class isn't exhausted → **deepen**
   (PPO → PPO+hparam, new `optimizer` idea, same scaffold). On plateau or exhausted class
   → **escalate** (PPO → GRPO, same anchor, new approach-class, new scaffold). This is the
   mechanism that turns "PPO is failing" into a decision.
5. **Trend layer** — over one anchor's append-only log: best-so-far, gain/session,
   cost/improvement, variance bands. Read-only input to (4) and the "long-running results"
   view. Trend the *science* (metric vs compute), never the *self* — keeps R3 clear of #5.

## Layer 1 — Sharper single session (harness)

Concept: the director must not be poisoned or buried by its own children. Defensive
plumbing, mostly mechanical.

- **Context cap at source** — `read_artifacts.py`/`check_children.py` return metrics-first,
  byte-ceiled, one job_id at a time; thin PostToolUse Bash backstop. (Fix the same
  too-late mechanism in `cap_web_fetch.py`.)
- **Verification gate** — director recomputes `delta_vs_baseline`; `validated:true`
  requires a matching `metrics.json` artifact. (This *is* the unifying primitive's gate.)
- **Sanitize child strings** before they hit director context (prompt-injection surface,
  amplified by `--dangerously-skip-permissions`).
- **Dispatch robustness** — write the audit record *after* a successful push (kills the
  permanent-stuck retry bug); lock the frozen scaffold after dispatch #1 (kills silent
  cross-sibling drift); backoff + jitter + `poll_sec` floor + explicit timeout signal.

## Layer 2 — Continuity across chats

Concept: a real advisor carries facts and taste between meetings, not transcripts.
Add the *right* memory; deliberately forget prose.

- **Findings ledger** (the primitive) scoped per user.
- **Killed-ideas graveyard** — `{idea, why, conditions}`; checked before proposing, and
  surfaced to the user ("we already ruled this out").
- **Baseline leaderboard** — canonical `{env, algo, seed, metric}`; skip re-running.
- **User-taste model (light)** — a few signals (final-return vs sample-efficiency,
  blunt negatives, concision). Not a preference learner.
- **User-approved synthesis summaries** (~200 words) replace raw transcripts as the
  cross-session carry.
- Forget: interpretation/narrative. Risk to design against: **hallucinated authority** —
  every fact carries confidence + date + evidence link; standing hypotheses are re-verified.

## Layer 3 — Self-improvement over a long-horizon goal

Concept: regenerate the plan fresh from the fact base each session; let structure emerge
over *results*, not plans. Rejected default: persisted hierarchical plan trees (they rot,
compound stale assumptions, and have no neutral garbage collector).

- **Regenerate-from-ledger** — feed the model the conditions-stamped facts + graveyard;
  it re-derives a coherent plan in one pass. Lean into the LLM's replanning strength.
- **Scar-tissue priors** — persist learned `(μ,σ)` per hyperparameter instead of resetting
  to uniform. Fact-shaped, not plan-shaped.
- **Anti-bias rotation** — if the last N syntheses favored one `diversity_tag`, the next
  plan excludes it. Fights convergence to a local optimum.
- **Wildcards to pilot later** (emergent, no plan tree): stigmergy (decaying reward-region
  markers guiding exploration), reputation market (Elo over sub-agent archetypes → budget).

## Where the changes live (skills · hooks · scripts · local store)

Local-first by design: the ledger is plain files the scripts own —
`./.ledger/findings.jsonl` (append-only, immutable, conditions-stamped) +
`./.ledger/artifacts/<finding_id>/` (plots, metric curves, checkpoints). **Durability
seam:** `ledger.py` syncs this dir to durable storage (runner/GCS) on session boundaries,
since the Cloud Run container is ephemeral. Trends/recall read the *local* copy and never
hit the network.

**Scripts** (`scripts/`)
- `ledger.py` — local Findings Store: `append` / `query` / `recall` + the sync seam.
- `verify_finding.py` — the gate: recompute `delta_vs_baseline` from raw metrics, confirm
  a matching artifact exists, outlier-check. Pass → eligible to persist.
- `trends.py` — per-anchor aggregation: best-so-far, gain/session, cost/improvement,
  variance; writes a compact digest + a PNG into local artifacts.
- `escalate.py` — reads `trends.py`, returns the deepen-vs-escalate recommendation.
- `recall.py` — top-k relevant findings for the current goal/anchor (used by the inject
  hook + research skill).

**Hooks** (`.claude/hooks/`) — everything context-related
- `cap_bash_output.py` (NEW, PostToolUse · Bash) — backstop cap on
  `read_artifacts`/`check_children`. Source caps go *inside* those scripts too.
- fix `cap_web_fetch.py` — replace `decision:block` (runs too late) with output-rewrite,
  the field that actually shrinks what the model next sees.
- `recall_inject.py` (NEW, SessionStart/UserPromptSubmit) — injects the *capped*
  recalled-findings digest into the director's opening context. How a new chat knows
  prior results (R1).
- `validate_finding.py` (NEW, PreToolUse · Bash matching the persist call) — enforces the
  trust invariant: rejects any ledger write lacking verification + conditions-stamp +
  citation. Mirrors `validate_dispatch.py`.

**Skills** (`skills/`)
- `research` (existing) — before planning: `recall.py` + `escalate.py` → regenerate a
  fresh plan carrying a `campaign_anchor` and an `approach_class` per idea.
- `dispatch-subagents` (existing) — stamp each idea with anchor + approach-class + a cost
  expectation.
- `synthesize` (NEW) — end-of-session: verify results, write findings through the gate,
  emit opinionated *cited* claims, refresh the approach-class rollup + trends.

**Schema** (`scripts/schemas.py`) — add `Finding`, `CampaignAnchor`, `approach_class`;
persist `validated` + reasoning (currently dropped).

## Sequencing

- **P0 — Harness hardening (L1).** `cap_bash_output.py` + source caps, fix
  `cap_web_fetch.py`, dispatch fixes, sanitize, poll backoff. No schema change. Do first.
- **P1 — Verification gate + local Findings Store (the trunk).** `schemas.Finding`,
  `ledger.py`, `verify_finding.py`, `validate_finding.py`. Closes L1 trust *and* founds
  L2/L3.
- **P2 — Cross-chat continuity (L2).** `recall.py` + `recall_inject.py` + `synthesize`
  skill + research-skill recall; graveyard/leaderboard/taste/approved-summaries on the P1
  store. Needs `mode != oneshot` (seam stubbed in `internal_api.py` bootstrap).
- **P3 — Long-horizon (L3).** `trends.py` + `escalate.py` + research-skill escalation +
  scar-tissue priors + anti-bias rotation. Then pilot one emergent wildcard (stigmergy or
  reputation market).

Explicitly **not** doing: persisted hierarchical plan trees; a heavyweight user-preference
learner; trusting any self-reported number. If it's ever easier to write a plan to disk than
a validated finding, the design is backwards.

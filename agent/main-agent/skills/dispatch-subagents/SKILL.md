---
name: dispatch-subagents
description: Use IMMEDIATELY after the research skill writes ./.dispatched/plan.json, to fan out one sub-agent container per idea. Invokes scripts/dispatch_subagent.py via Bash (one call per idea), then polls children over HTTP with scripts/check_children.py / wait_for_children.py, then synthesizes. Invoke also when re-dispatching a subset after a synthesis pass.
---

# Dispatch Subagents Skill

You have a validated `./.dispatched/plan.json`. Each idea becomes one
sub-agent container. The consistency contract is enforced by the schema +
PreToolUse hook, so you cannot accidentally dispatch a mismatched job.

## The deterministic script

The only way to dispatch is `scripts/dispatch_subagent.py`. Invoke via `Bash`:

```bash
python3 scripts/dispatch_subagent.py \
  --plan ./.dispatched/plan.json \
  --idea-id idea_<id>
```

Exit codes:
- `0` — dispatched (one JSON line on stdout with `job_id`, `out_path`)
- `1` — bad args or filesystem error
- `2` — schema or consistency validation failed (reason on stderr)

On success, the script writes a local audit copy to `./.dispatched/<job_id>.json`
AND POSTs the dispatch record to the runner's `/internal/dispatch`. The runner
(outside this container — you do NOT share a filesystem with it or with the
sub-agents) registers the job, spawns a sub-agent, mounts the record into the
sub-agent's volume, and collects its RunResult. You observe results over HTTP via
the helper scripts below — not by reading local files.

## Procedure

1. **Sanity check the plan.**

   ```bash
   python3 -c "import json, sys; sys.path.insert(0,'scripts'); \
     from schemas import ResearchPlan; \
     p = ResearchPlan.model_validate(json.load(open('./.dispatched/plan.json'))); \
     print(f'plan={p.id} ideas={[i.id for i in p.ideas]}')"
   ```

2. **Dispatch one sub-agent per idea**, in any order. Issue each as a
   separate `Bash` tool call so the PreToolUse hook validates each one:

   ```bash
   python3 scripts/dispatch_subagent.py --plan ./.dispatched/plan.json --idea-id idea_xxx
   ```

3. **Handle errors immediately**.
   - Exit 2 = the plan or idea is invalid; re-enter the `research` skill to
     fix the plan. Do NOT retry blindly.
   - Stderr "already dispatched in this plan" = you tried to dispatch the
     same idea twice. Skip it.
   - Exit 1 = filesystem/arg issue; fix the path or the script call.

4. **Wait for RunResults over HTTP — do NOT synthesize early** (no shared
   filesystem). A sub-agent training `budget_steps` on a CPU learner can take many
   minutes to tens of minutes; if you synthesize before it lands, its result is
   silently excluded and the round is wasted. So you MUST block on
   `wait_for_children` (exit 0 = all terminal) before step 5. Use the helper
   scripts, which query the runner's internal API:

   ```bash
   python3 scripts/check_children.py                  # <jid> <status> <summary> per child
   # Block until ALL children are terminal. Derive the timeout from the plan's
   # wall-clock budget so you wait long enough for the slowest run:
   TIMEOUT=$(python3 -c "import json,sys; sys.path.insert(0,'scripts'); \
     from schemas import ResearchPlan; \
     print(ResearchPlan.model_validate(json.load(open('./.dispatched/plan.json'))).wait_timeout_seconds())")
   python3 scripts/wait_for_children.py j_a j_b --timeout "$TIMEOUT"
   python3 scripts/read_artifacts.py j_a               # a child's artifact refs (gs:// urls)
   ```

   Each child's status is `running | done | failed`; `done` rows carry the
   sub-agent's summary. Don't poll faster than ~5s. If `wait_for_children` times
   out (exit 2) it prints the still-pending ids — note them as incomplete in your
   synthesis rather than pretending they finished.

5. **Synthesize.** Only after `wait_for_children` returns 0, rank by `plan.target_metric`.
   Write a 10-30 line synthesis covering:
   - Which ideas moved the metric, by how much, vs the baseline encoded in
     `plan.base_hparams`.
   - Which ideas didn't move it and why (use the sub-agent's own diagnosis).
   - One next-step recommendation: extend the winner, kill the losers, or
     iterate the plan and re-dispatch.

   Save the synthesis to `./.dispatched/synthesis.md`.

## Hard rules

- One Bash call per dispatch — never chain `&&` to dispatch two ideas in one
  call (the hook only sees the first one cleanly).
- Never edit `plan.base_hparams`, `plan.reward_fn_spec`, `plan.env_id`, or
  `plan.target_metric` between dispatches in a single round. If you need to
  change any of those, that is a NEW plan: rebuild it via the `research`
  skill and dispatch fresh.
- Never dispatch the same `idea_id` twice — the hook rejects it, but don't
  rely on the hook; track your own dispatched ids.
- If a RunResult has `status: failed`, look at its summary before
  re-dispatching anything. Re-dispatching a failed idea unchanged just burns
  budget.

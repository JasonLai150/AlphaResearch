---
name: dispatch-subagents
description: Use IMMEDIATELY after the research skill writes ./.dispatched/plan.json, to fan out one sub-agent container per idea. Invokes scripts/dispatch_subagent.py via Bash (one call per idea), then waits for RunResult JSON files in ./.dispatched/, then synthesizes. Invoke also when re-dispatching a subset after a synthesis pass.
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

On success, the script writes the dispatch record to
`./.dispatched/<job_id>.json`. The runner (outside this container) watches
that directory, spawns a sub-agent container for each new record, mounts the
record at `/workspace/job.json` inside the sub-agent, and writes the
sub-agent's RunResult back to `./.dispatched/<job_id>.result.json`.

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

4. **Wait for RunResults**. The runner writes
   `./.dispatched/<job_id>.result.json` for each completed sub-agent. Poll:

   ```bash
   ls ./.dispatched/*.result.json 2>/dev/null
   ```

   The RunResult JSON shape is the sub-agent's responsibility (see
   `agent/sub-agent/CLAUDE.md`), but at minimum contains
   `{job_id, idea_id, status, summary, metrics}`.

5. **Synthesize.** Read each `*.result.json`. Rank by `plan.target_metric`.
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

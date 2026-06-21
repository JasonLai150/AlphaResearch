---
name: validated-findings
description: Use when deciding whether to STOP the experimentation loop and write /workspace/result.json. Defines the bar for "validated finding" — positive or negative — so the sub-agent doesn't quit too early on noise or keep burning budget chasing variance.
---

# Validated Findings

A finding is *validated* when ALL of the following are true:

1. **Baseline exists and is real.** You ran the unmodified `plan.base_hparams`
   setup at least once on `plan.env_id` for the full `plan.budget_steps`, and
   recorded `plan.target_metric` at the end. No fabricated baselines.
2. **Intervention was actually applied.** You can point to the line(s) of code
   or config that implement `idea.approach` and they are NOT no-ops.
3. **Run is complete.** The training run hit `plan.budget_steps` (no early
   abort), or you have a documented reason it terminated early that doesn't
   invalidate the metric (e.g. eval converged).
4. **Multi-seed evidence.** At least 2 seeds for the intervention. One seed is
   not a finding — it's a sample.
5. **Comparison is honest.** `delta_vs_baseline = intervention_mean -
   baseline_mean`, both reported with seed counts. Don't cherry-pick.
6. **The success criterion is testable.** You can answer "yes/no" to
   `idea.success_criterion` from the numbers, not from intuition.

A **positive** validated finding: success_criterion met, delta is outside
1-seed noise on the baseline.

A **negative** validated finding: at least 2 honest seeds attempted, no
movement (or movement smaller than baseline 1-seed noise). Write
`validated: false` with `validation_reasoning` explaining why the negative
result is itself informative (e.g. "this entire diversity_tag axis appears
ineffective for this env").

## When NOT to stop yet

- You have only 1 seed of the intervention and budget remains → run another
  seed.
- The training curve is still rising at `budget_steps` → note it but you
  cannot extend the budget; report `partial` and explain.
- You found a bug in your implementation mid-run → fix, re-run, do NOT
  include the buggy run in metrics.
- You ran out of time on the wall clock but not on `plan.budget_steps` →
  report `partial` with what you have. Do not pad.

## When to stop early (before budget)

- `success_criterion` is so conclusively met that more seeds are obvious
  (e.g. 5x better than baseline on first 2 seeds) — write the result.
- You've tried 3 distinct variants of your intervention and none moved the
  metric — write a negative validated finding and stop. Don't burn budget on
  variant 4 of a dead idea.
- The container is about to be killed (wall clock budget) — write whatever
  you have with `status: "partial"`.

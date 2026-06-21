---
name: research
description: Use at the start of every research session, before any dispatch. Turns a vague user goal into one ResearchPlan JSON object containing the FROZEN consistency scaffold (env, reward, base hparams, target metric, budget) plus 2-5 DIVERSE, opinionated ideas that have survived an adversarial review pass. Invoke whenever the user gives a research goal, the plan needs revision after sub-agent results return, or before invoking the dispatch_subagent.py script.
---

# Research Skill

Convert "user wants X" → one `ResearchPlan` JSON file at `./.dispatched/plan.json`.
That file is the single source of truth: the dispatch skill reads it, the
deterministic dispatch script revalidates it, and the PreToolUse hook
revalidates it again on every `Bash` call. If it's malformed, you cannot
dispatch.

## Output: the ResearchPlan object

Schema lives in `scripts/schemas.py` (`ResearchPlan`, `ResearchIdea`,
`DiversityTag`). Write JSON in this shape:

```json
{
  "id": "plan_<auto>",
  "goal": "<user goal, restated precisely>",
  "env_id": "<single env id, e.g. MiniGrid-DoorKey-8x8>",
  "reward_fn_spec": "<one paragraph describing the reward; FROZEN across sub-agents>",
  "base_hparams": { "<name>": "<value>", "...": "..." },
  "target_metric": "<single scalar metric, e.g. mean_return_at_500k_steps>",
  "budget_steps": 500000,
  "ideas": [
    {
      "id": "idea_<auto>",
      "title": "<short-kebab-tag>",
      "diversity_tag": "exploration | reward_shaping | architecture | optimizer | regularization | data | algorithm | other",
      "hypothesis": "<1-3 sentences: what you expect to happen and why>",
      "approach": "<concrete intervention the sub-agent will implement>",
      "success_criterion": "<observable result that would validate this idea>",
      "expected_metric_delta": 0.05
    }
  ]
}
```

You can omit auto-generated `id` fields; the schema fills them in. The
PreToolUse hook will reject the dispatch if:

- `< 2` or `> 5` ideas
- duplicate idea ids or titles
- one `diversity_tag` dominates (more than `ceil(n/2)` ideas share it)
- `base_hparams` is empty
- any required field is empty / missing

## Process (do each phase, in order)

### Phase 1 — broad information

Spend 5-15 minutes max, then STOP.

- Read `../../README.md`, `../../docs/`, and any
  `../../meta-planning/docs/plan.md` for prior context.
- `WebSearch` for the goal's domain ("PPO MiniGrid sample efficiency 2024",
  etc.). Read 2-4 strong sources via `WebFetch` — the PostToolUse hook caps
  each at ~12 KB, so be specific about which page/section you want. Prefer
  survey papers, recent benchmarks, ablation studies over blog posts.
- Note baseline numbers and what state-of-the-art looks like. You need this
  to set a realistic `expected_metric_delta`.

Stop when you have: (a) a defensible baseline metric value, (b) ≥6 candidate
intervention ideas, (c) a sense of which diversity axes most likely move the
metric in this env.

### Phase 2 — generate ≥6 candidate ideas

Brainstorm broadly. Cover MULTIPLE `diversity_tag` axes — do not produce 6
exploration ideas. Each candidate needs `title`, `diversity_tag`, `hypothesis`,
`approach` (one sentence each at this stage).

### Phase 3 — adversarial review (non-negotiable)

Attack each candidate on:

1. **Redundancy** — would this collapse to another candidate's result?
2. **Confounding** — does it require changing `base_hparams` or
   `reward_fn_spec`? If yes, either kill it, or absorb the change into the
   scaffold and update ALL other ideas to share the new scaffold.
3. **Compute fit** — can a sub-agent run it within `budget_steps`?
4. **Falsifiability** — is `success_criterion` something you can read off
   the sub-agent's RunResult numerically, not a vibe?
5. **Boring prior** — is this just "tune the LR"? Kill it unless the prior
   literature explicitly shows it's the dominant lever for this env.

Useful self-attack: write a `## Adversarial review` section in
`./.dispatched/plan.scratch.md` that ONLY tries to break each idea. Keep
survivors.

### Phase 4 — reduce to 2-5 diverse ideas, write the plan

- Lock the scaffold. `env_id`, `reward_fn_spec`, `base_hparams`,
  `target_metric`, `budget_steps` are FROZEN. Pick `base_hparams` matching the
  strongest published baseline from Phase 1 (that's the control).
- Pick 2-5 surviving ideas, distributed across `diversity_tag`s. Diversity
  cap: no single tag may hold more than `ceil(n/2)` ideas (e.g. 3 ideas → max
  2 per tag; 5 ideas → max 3 per tag).
- Write the JSON to `./.dispatched/plan.json`:

  ```bash
  mkdir -p ./.dispatched && cat > ./.dispatched/plan.json <<'EOF'
  { ...plan... }
  EOF
  ```

- Quick local sanity check before dispatch:

  ```bash
  python3 -c "import json, sys; sys.path.insert(0,'scripts'); \
    from schemas import ResearchPlan; \
    ResearchPlan.model_validate(json.load(open('./.dispatched/plan.json'))); \
    print('plan ok')"
  ```

  If this fails, fix the JSON before invoking the dispatch skill.

- Add a 1-3 line entry to `../../meta-planning/docs/plan.md` per the repo's
  CLAUDE.md.

### Phase 5 — hand off

Summarize for the user (5-15 lines):

- What scaffold you locked and why those `base_hparams`.
- What 2-5 ideas you're testing and the diversity axis each one covers.
- What would count as "this session was worth it" (metric thresholds).

Then invoke the `dispatch-subagents` skill.

## Red flags — refuse to proceed

- "Just dispatch and see what happens" — without a frozen scaffold, results
  aren't comparable.
- All ideas share one `diversity_tag` — not diverse.
- `base_hparams = {}` — schema rejects it; you're not actually controlling.
- `target_metric` is a tuple ("return AND wall-clock") — pick ONE.
- `expected_metric_delta` is 0 for every idea — you don't believe your own
  plan; iterate.

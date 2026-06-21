---
name: plotly-graphs
description: Use during synthesis (after sub-agent results return) to produce beautiful, deterministic Plotly graphs of the findings. You write declarative GraphSpec JSON to ./.graphs/specs/<id>.json — data and labels only, never plotting code — then run scripts/render_graph.py to turn each spec into a themed Plotly figure the frontend can render. A PostToolUse hook validates every spec's format on write. Invoke whenever you want to show a comparison: per-idea deltas vs baseline, metric-vs-steps training curves, or cost/return scatter.
---

# Plotly Graphs Skill

Turn your synthesis into figures the user (and the frontend) can actually see.
**You never write Plotly code.** You write a small JSON *spec* describing the
data; a deterministic script owns all the styling. Same spec → same beautiful
graph, every time.

## Why it works this way

If the agent hand-wrote Plotly, every graph would look different and many would
break. Instead the contract is split:

- **You supply content**: chart kind, title, axis labels, named data series.
- **`scripts/render_graph.py` supplies aesthetics**: a fixed template, colorway,
  fonts, and layout. It re-validates your spec, so a malformed graph can't slip
  through to the frontend.

## Step 1 — write a GraphSpec

Write one JSON file per graph to `./.graphs/specs/<id>.json`. `<id>` is a kebab
slug and becomes the output filename. Shape (schema: `scripts/schemas.py:GraphSpec`):

```json
{
  "id": "return-vs-steps",
  "kind": "line",
  "title": "Mean return vs training steps",
  "x_label": "env steps",
  "y_label": "mean return",
  "series": [
    {"name": "ppo+icm",  "x": [0, 250000, 500000], "y": [0.0, 0.40, 0.82], "error_y": [0.0, 0.05, 0.03]},
    {"name": "baseline", "x": [0, 250000, 500000], "y": [0.0, 0.30, 0.55]}
  ],
  "caption": "ICM intrinsic reward; mean ± std over 3 seeds.",
  "meta": {"env_id": "MiniGrid-DoorKey-8x8", "target_metric": "mean_return_at_500k_steps"}
}
```

Rules the validator enforces (a PostToolUse hook checks on every write):

- `kind` ∈ `line` | `bar` | `scatter`.
- `title` and `id` non-empty; at least one `series`.
- Within a series, `x` and `y` are equal length; optional `error_y` matches `y`.
- Data only — no colors, no layout, no styling. Those are not yours to set.

If the hook reports an error, fix the spec and rewrite it.

## Step 2 — render it

```bash
python3 scripts/render_graph.py .graphs/specs/<id>.json
```

This validates the spec again and writes a Plotly figure to
`.graphs/rendered/<id>.json` (exit 3 if the spec is malformed — fix and re-run).
That figure JSON is exactly what the frontend's plotly.js consumes; it is shipped
onward later. List the rendered path in your synthesis.

## What to graph (and what not to)

Make graphs that carry an opinionated claim, not decoration:

- **Per-idea delta vs baseline** (`bar`) — one bar per idea on `target_metric`. The
  money chart of a session.
- **Metric vs steps** (`line`) — learning curves per idea + baseline; use `error_y`
  for seed std so the reader sees signal vs noise.
- **Cost vs return** (`scatter`) — when compute differs across ideas.

Do NOT graph a single number, or anything you can't back with a sub-agent's real
metrics. A graph asserting an unverified result is worse than no graph.

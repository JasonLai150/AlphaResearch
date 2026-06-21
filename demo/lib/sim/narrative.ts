import { pick, type Rng } from "@/lib/sim/rng";
import type { Scenario, StrategySpec } from "@/lib/sim/types";

/*
  Templated, RNG-varied prose. Keeps the chat reading fresh and goal-relevant
  without an LLM. Lead-agent turns go into the main transcript; per-researcher
  work-log lines are consumed by the /view inspector (NOT the chat).
*/

const fmt = (x: number) => x.toFixed(2);

export function label(i: number): string {
  return String.fromCharCode(65 + i);
}

/** Lead-agent progress update once the first pilots report in. */
export function leadProgress(scn: Scenario): string {
  const ranked = scn.strategies
    .map((s, i) => ({ s, i, r: s.points[Math.floor(s.points.length * 0.45)].reward }))
    .sort((a, b) => b.r - a.r);
  const lines = ranked.map(({ s, i, r }) => {
    if (s.outcome === "fail")
      return `• ${label(i)} (${s.kind}) is stuck near ${fmt(r)} — not separating from the baseline.`;
    if (s.outcome === "win")
      return `• ${label(i)} (${s.kind}) is already at ${fmt(r)} ${scn.metricName} and still climbing.`;
    return `• ${label(i)} (${s.kind}) sits at ${fmt(r)} and is climbing slowly.`;
  });
  return `First signal from the pilots (${scn.strategies[0].seeds} seeds each):\n${lines.join(
    "\n"
  )}`;
}

/** Lead-agent final recommendation once everything has reported. */
export function leadFinal(scn: Scenario): string {
  const w = scn.strategies[scn.winnerIdx];
  const wl = label(scn.winnerIdx);
  const final = w.points[w.points.length - 1].reward;
  const runnerUp = scn.strategies
    .map((s, i) => ({ s, i }))
    .filter(({ i }) => i !== scn.winnerIdx)
    .sort((a, b) => b.s.target - a.s.target)[0];
  return [
    `${wl} (${w.kind}) is the clear winner — it reaches ${fmt(final)} ${scn.metricName}, well past the ${fmt(
      scn.baseline
    )} plateau, and the gain holds on held-out seeds rather than chasing the reward bonus.`,
    runnerUp
      ? `Recommendation: promote ${wl} to the full run and fold ${label(runnerUp.i)} (${runnerUp.s.kind}) in as an ablation. The rest can wait for a free runner.`
      : `Recommendation: promote ${wl} to the full run.`,
  ].join("\n\n");
}

/** A finished sub-agent's one-paragraph summary (rides a `summary` event). */
export function strategySummary(scn: Scenario, spec: StrategySpec, i: number): string {
  const final = spec.points[spec.points.length - 1].reward;
  if (spec.outcome === "fail")
    return `${label(i)} (${spec.kind}): plateaued at ${fmt(final)} ${scn.metricName}; the change didn't separate from the ${fmt(
      spec.baseline
    )} baseline. Not worth scaling.`;
  if (spec.outcome === "win")
    return `${label(i)} (${spec.kind}): reached ${fmt(final)} ${scn.metricName} over ${spec.seeds} seeds — a clean break from the plateau. Extrinsic-only eval confirms it's solving the task, not gaming the bonus.`;
  return `${label(i)} (${spec.kind}): improved to ${fmt(final)} ${scn.metricName}; promising but still climbing at the budget cutoff.`;
}

const THINK_TEMPLATES = [
  (s: StrategySpec) => `Booting sandbox · ${s.kind}. Cloning the ${s.id} worktree.`,
  () => `Reading runner config and the last three baseline runs.`,
  (s: StrategySpec) => `${s.blurb}`,
  () => `Patched the module; launching training over ${"{seeds}"} seeds.`,
  () => `Training… watching ${"{metric}"} and the value loss.`,
  () => `Eval checkpoint: holding out 64 episodes to separate task reward from shaping.`,
  () => `Rendering a rollout to eyeball the failure modes.`,
  () => `Writing the summary and reporting back up to the lead.`,
];

/** Per-researcher work-log lines (for the /view inspector's live work log). */
export function workLog(scn: Scenario, spec: StrategySpec, rng: Rng): string[] {
  return THINK_TEMPLATES.map((t) =>
    t(spec).replace("{seeds}", String(spec.seeds)).replace("{metric}", scn.metricName)
  ).concat(
    spec.outcome === "win"
      ? [`Clean signal — flagging this as the winner.`]
      : spec.outcome === "fail"
        ? [`No separation from baseline; marking inconclusive.`]
        : [`Still climbing at cutoff; recommending a longer run.`]
  );
  // (rng reserved for future variation; kept deterministic for now)
}

/** A short, varied tool-call description for the lead's planning phase. */
export function planningTool(rng: Rng): { tool: string; note: string } {
  return pick(rng, [
    { tool: "read_config", note: "runner/configs" },
    { tool: "query_wandb", note: "last 3 runs" },
    { tool: "open_worktrees", note: "isolated sandboxes" },
  ]);
}

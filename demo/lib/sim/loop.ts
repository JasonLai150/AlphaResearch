import { buildScenario } from "@/lib/sim/scenario";
import { clamp, gaussian, mulberry32, seedFromString } from "@/lib/sim/rng";

/*
  Autonomous-loop model, faithful to meta-planning/docs/autonomous-loops.md: a
  session runs many ROUNDS toward a goal. Each round is a fresh research run that
  reports a best metric; the "runner" applies a pure stop policy at each round
  boundary and either spawns the next round or marks the loop terminal. The
  best metric improves with diminishing returns, then plateaus.

  Terminal STATUS is one of: completed | stopped | budget_exhausted | failed.
  For `completed`, a REASON records why (goal_metric / max_rounds / plateau).
*/

export type LoopStatus = "running" | "completed" | "stopped" | "budget_exhausted" | "failed";
export type StopReason = "goal_metric" | "max_rounds" | "plateau" | "user" | null;

export interface LoopRound {
  round_index: number;
  best_metric: number;
  prev_best: number;
  improved: boolean;
  /** A few sub-agent results that fed this round's synthesis. */
  sub_rewards: number[];
  plan: string;
  summary: string;
  /** Mean training loss / efficiency for the round (cross-round curves). */
  loss: number;
  efficiency: number;
}

export interface LoopPlan {
  goal: string;
  env: string;
  algo: string;
  metricName: string;
  baseline: number;
  goalMetric: number;
  maxRounds: number;
  plateauK: number;
  /** The full pre-computed round sequence up to the natural terminal round. */
  rounds: LoopRound[];
  stopReason: Exclude<StopReason, "user" | null>;
}

const ROUND_PLANS = [
  "Scope the goal and run a broad sweep across the top directions.",
  "Deepen the leading direction; tighten the reward and re-run.",
  "Add an ablation against the runner-up and extend the budget.",
  "Harden the winner: longer horizon, more seeds, held-out eval.",
  "Push for the goal metric; trim everything that isn't separating.",
  "Squeeze the last gains; confirm the result is stable across seeds.",
  "Diminishing returns — re-running to confirm the plateau holds.",
  "Final confirmation round at the current best configuration.",
];

export function buildLoopPlan(
  goal: string,
  maxRounds: number,
  goalMetric: number,
  plateauK = 2,
  seed = seedFromString(goal)
): LoopPlan {
  const scn = buildScenario(goal, seed);
  const rng = mulberry32(seed ^ 0x51ed270b);
  const baseline = scn.baseline;
  // Ceiling the loop can asymptotically reach (just under perfect).
  const ceiling = clamp(baseline + (1 - baseline) * (0.8 + rng() * 0.15), baseline + 0.15, 0.98);
  const rate = 0.45 + rng() * 0.25;

  const rounds: LoopRound[] = [];
  let runningBest = baseline;
  let sinceImprove = 0;
  let stopReason: LoopPlan["stopReason"] = "max_rounds";

  for (let r = 0; r < maxRounds; r++) {
    // Round 0 is the baseline sweep (sits at baseline); the climb starts at r=1.
    const ideal = baseline + (ceiling - baseline) * (1 - Math.exp(-r * rate));
    const noisy = clamp(ideal + gaussian(rng, 0, 0.012), 0, 1);
    const prev = runningBest;
    const best = Math.max(runningBest, noisy); // best metric is a running max
    const improved = best > prev + 0.005;
    runningBest = best;
    sinceImprove = improved ? 0 : sinceImprove + 1;

    const subs = [0, 1, 2].map(() => clamp(best - Math.abs(gaussian(rng, 0.05, 0.05)), 0, 1));
    rounds.push({
      round_index: r,
      best_metric: best,
      prev_best: prev,
      improved,
      sub_rewards: subs,
      plan: ROUND_PLANS[Math.min(r, ROUND_PLANS.length - 1)],
      summary: roundSummary(r, best, prev, improved, scn.metricName),
      loss: clamp(0.9 * Math.exp(-0.5 * (r + 1)) + 0.08 + gaussian(rng, 0, 0.01), 0.02, 2),
      efficiency: clamp(0.7 - 0.07 * r + gaussian(rng, 0, 0.02), 0.05, 1),
    });

    // Stop policy (priority: goal_metric > plateau > max_rounds).
    if (best >= goalMetric) {
      stopReason = "goal_metric";
      break;
    }
    if (sinceImprove >= plateauK) {
      stopReason = "plateau";
      break;
    }
    if (r === maxRounds - 1) {
      stopReason = "max_rounds";
      break;
    }
  }

  return {
    goal: scn.goal,
    env: scn.env,
    algo: scn.algo,
    metricName: scn.metricName,
    baseline,
    goalMetric,
    maxRounds,
    plateauK,
    rounds,
    stopReason,
  };
}

function roundSummary(
  r: number,
  best: number,
  prev: number,
  improved: boolean,
  metric: string
): string {
  const delta = best - prev;
  if (r === 0) return `Round 1 baseline sweep — best ${metric} ${best.toFixed(3)}.`;
  if (improved)
    return `Round ${r + 1}: best ${metric} ${best.toFixed(3)} (+${delta.toFixed(3)}). Carrying the winner forward.`;
  return `Round ${r + 1}: best ${metric} held at ${best.toFixed(3)} (no new best). Approaching a plateau.`;
}

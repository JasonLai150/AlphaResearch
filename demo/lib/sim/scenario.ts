import { clamp, gaussian, int, mulberry32, sample, type Rng } from "@/lib/sim/rng";
import type { CurvePoint, Outcome, Scenario, StrategySpec } from "@/lib/sim/types";

/*
  Turns any goal string into a plausible RL research plan: detects the env /
  algorithm / metric, then samples a handful of independent strategy directions
  from a library, each with a precomputed training curve. Pure + deterministic
  given (goal, seed).
*/

interface StrategyTemplate {
  id: string;
  kind: string;
  blurb: string;
  /** Bias on how much headroom this direction tends to unlock (0–1). */
  strength: number;
  tools: string[];
}

const LIBRARY: StrategyTemplate[] = [
  {
    id: "icm",
    kind: "Curiosity (ICM)",
    blurb:
      "Add an intrinsic curiosity bonus for novel states to drive exploration.",
    strength: 0.9,
    tools: ["read_config", "edit_reward_module", "launch_training", "eval_policy", "render_rollout"],
  },
  {
    id: "shaping",
    kind: "Subgoal reward shaping",
    blurb: "Dense shaped reward for key pickup and reaching the door.",
    strength: 0.72,
    tools: ["read_config", "patch_env_wrapper", "launch_training", "eval_policy"],
  },
  {
    id: "gae",
    kind: "GAE-λ + batch sweep",
    blurb: "Sweep GAE-λ and batch size to stabilize the advantage estimates.",
    strength: 0.5,
    tools: ["read_config", "grid_search", "launch_training", "plot_metrics"],
  },
  {
    id: "lstm",
    kind: "Frame-stack + LSTM policy",
    blurb: "Recurrent policy over stacked frames for partial observability.",
    strength: 0.63,
    tools: ["read_config", "edit_policy_net", "launch_training", "eval_policy"],
  },
  {
    id: "entropy",
    kind: "Entropy coefficient schedule",
    blurb: "Anneal the entropy bonus to trade exploration for exploitation.",
    strength: 0.41,
    tools: ["read_config", "edit_hyperparams", "launch_training", "plot_metrics"],
  },
  {
    id: "sac",
    kind: "SAC baseline",
    blurb: "Off-policy SAC baseline for sample-efficiency comparison.",
    strength: 0.55,
    tools: ["read_config", "swap_algorithm", "launch_training", "eval_policy"],
  },
  {
    id: "per",
    kind: "Prioritized replay",
    blurb: "Prioritize high-TD-error transitions to speed up credit assignment.",
    strength: 0.58,
    tools: ["read_config", "edit_buffer", "launch_training", "plot_metrics"],
  },
  {
    id: "curriculum",
    kind: "Curriculum schedule",
    blurb: "Grow grid size gradually so the policy bootstraps from easy levels.",
    strength: 0.66,
    tools: ["read_config", "build_curriculum", "launch_training", "eval_policy"],
  },
];

const ENV_PATTERNS: [RegExp, string][] = [
  [/door\s*key|doorkey/i, "MiniGrid-DoorKey-8x8"],
  [/minigrid/i, "MiniGrid-MultiRoom-N6"],
  [/atari|breakout|pong/i, "ALE/Breakout-v5"],
  [/mujoco|halfcheetah|humanoid|ant\b/i, "MuJoCo-HalfCheetah-v4"],
  [/cartpole/i, "CartPole-v1"],
  [/lunar/i, "LunarLander-v2"],
];

const ALGO_PATTERNS: [RegExp, string][] = [
  [/\bppo\b/i, "PPO"],
  [/\bsac\b/i, "SAC"],
  [/\bdqn\b/i, "DQN"],
  [/\ba2c\b/i, "A2C"],
  [/\bimpala\b/i, "IMPALA"],
];

function detect(patterns: [RegExp, string][], text: string, fallback: string) {
  for (const [re, val] of patterns) if (re.test(text)) return val;
  return fallback;
}

function detectBaseline(text: string, fallback: number): number {
  // "plateauing around 0.55", "stuck at 0.4 success"
  const m = text.match(/(?:around|at|near)\s*(0?\.\d+|\d{1,2}%)/i);
  if (!m) return fallback;
  const raw = m[1];
  if (raw.endsWith("%")) return clamp(parseFloat(raw) / 100, 0.05, 0.9);
  return clamp(parseFloat(raw), 0.05, 0.9);
}

/** A logistic 0→1 ramp centered at `mid` with steepness `k`. */
function logistic(p: number, mid: number, k: number): number {
  return 1 / (1 + Math.exp(-k * (p - mid)));
}

function buildCurve(
  rng: Rng,
  baseline: number,
  target: number,
  steps: number,
  outcome: Outcome,
  n = 18
): CurvePoint[] {
  const mid = outcome === "win" ? 0.32 : outcome === "fail" ? 0.8 : 0.48;
  const k = outcome === "win" ? 9 : outcome === "plateau" ? 5 : 7;
  const lossStart = 1.1 + rng() * 0.5;
  const lossEnd = 0.08 + rng() * 0.12;
  const pts: CurvePoint[] = [];
  for (let i = 0; i < n; i++) {
    const p = i / (n - 1);
    const ramp = logistic(p, mid, k) / logistic(1, mid, k);
    let reward = baseline + (target - baseline) * ramp;
    if (outcome === "fail") reward = baseline + (target - baseline) * 0.25 * ramp;
    reward = clamp(reward + gaussian(rng, 0, 0.018), 0, 1);
    const loss = clamp(
      lossStart * Math.exp(-2.4 * p) + lossEnd + gaussian(rng, 0, 0.02),
      0.02,
      2
    );
    const efficiency = clamp(
      ((reward - baseline) / Math.max(target - baseline, 0.01)) * (1 - 0.28 * p) +
        0.18 +
        gaussian(rng, 0, 0.02),
      0,
      1
    );
    pts.push({ step: Math.round(p * steps), reward, loss, efficiency });
  }
  return pts;
}

const LEAD_INTRO = (env: string, algo: string, metric: string, baseline: number) =>
  `Read the run config and the last few ${algo} runs on ${env}. The plateau near ${baseline.toFixed(
    2
  )} ${metric} lines up with the sparse reward — the policy rarely chains the full task inside the episode budget, so the advantage estimates stay noisy.`;

export function buildScenario(goal: string, seed: number): Scenario {
  const rng = mulberry32(seed);
  const text = goal || "Improve PPO sample efficiency on MiniGrid-DoorKey-8x8";
  const env = detect(ENV_PATTERNS, text, "MiniGrid-DoorKey-8x8");
  const algo = detect(ALGO_PATTERNS, text, "PPO");
  const metricName = /reward|return/i.test(text) ? "mean return" : "success rate";
  const baseline = detectBaseline(text, 0.55);

  const nStrategies = int(rng, 3, 4);
  const templates = sample(rng, LIBRARY, nStrategies);

  // Assign outcomes: exactly one winner, the rest climb/plateau, occasionally a fail.
  const winnerIdx = int(rng, 0, templates.length - 1);
  const strategies: StrategySpec[] = templates.map((t, i) => {
    let outcome: Outcome;
    if (i === winnerIdx) outcome = "win";
    else {
      const r = rng();
      outcome = r < 0.18 ? "fail" : r < 0.5 ? "plateau" : "climb";
    }
    const headroom = (1 - baseline) * t.strength;
    const target =
      outcome === "win"
        ? clamp(baseline + headroom * (0.85 + rng() * 0.15) + 0.08, baseline + 0.12, 0.98)
        : outcome === "fail"
          ? clamp(baseline + headroom * 0.3, baseline + 0.02, 0.99)
          : clamp(baseline + headroom * (0.45 + rng() * 0.3), baseline + 0.05, 0.97);
    const steps = [50_000, 75_000, 100_000][int(rng, 0, 2)];
    const seeds = [4, 6, 8][int(rng, 0, 2)];
    return {
      id: t.id,
      kind: t.kind,
      blurb: t.blurb,
      baseline,
      target,
      steps,
      seeds,
      outcome,
      points: buildCurve(rng, baseline, target, steps, outcome),
      tools: t.tools,
    };
  });

  const labels = strategies.map((s, i) => `${String.fromCharCode(65 + i)} — ${s.kind}`);
  const leadPlan = [
    LEAD_INTRO(env, algo, metricName, baseline),
    `Branching ${strategies.length} independent directions, each isolated in its own sandbox so they don't share state:`,
    labels.map((l) => `• ${l}`).join("\n"),
    `Running short pilots (${strategies[0].seeds} seeds each) and reporting ${metricName} back — I'll scale whichever direction clears the plateau.`,
  ];

  return { goal: text, seed, env, algo, metricName, baseline, leadPlan, strategies, winnerIdx };
}

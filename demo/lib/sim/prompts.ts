import { label } from "@/lib/sim/narrative";
import type { Scenario, StrategySpec } from "@/lib/sim/types";

/*
  Grounded prompt builders for the live (real-Claude) path. Every prompt pins the
  model to the deterministic scenario's numbers — env, algorithm, baseline,
  per-direction rewards, the winner — so the prose is genuinely model-written but
  the metrics stay reproducible and consistent with the curves/cards/inspector.
  The system prompt fixes the lead-agent voice; prompts carry the facts.
*/

const fmt = (x: number) => x.toFixed(2);

export const LEAD_SYSTEM = `You are the lead research agent in AlphaResearch, an autonomous reinforcement-learning research console. You coordinate a fleet of sub-agents, each testing one research direction in its own sandbox, and report up to a human researcher in a chat feed.

Voice: a sharp, senior ML researcher talking to a peer. Concrete and technical, never bubbly. Plain prose — no markdown headings, no bold, no emoji, no preamble like "Sure" or "Here is". Bullet points are fine when listing directions or results. Be concise: a short paragraph, or a few bullets.

Hard rule: use ONLY the numbers and facts given to you. Never invent metrics, step counts, or results. Refer to directions by their letter label exactly as given.`;

/** Compact, numeric facts block shared across lead prompts. */
function scenarioFacts(scn: Scenario): string {
  const dirs = scn.strategies
    .map((s, i) => `  ${label(i)}: ${s.kind} — ${s.blurb} (baseline ${fmt(s.baseline)}, target ${fmt(s.target)} ${scn.metricName}, ${s.seeds} seeds, ${s.steps.toLocaleString()} steps)`)
    .join("\n");
  return `Goal: ${scn.goal}
Environment: ${scn.env} · Algorithm: ${scn.algo} · Metric: ${scn.metricName} · Current baseline: ${fmt(scn.baseline)}
Directions you are about to run:
${dirs}`;
}

/** Opening plan — streamed as the first lead turn, before sub-agents spawn. */
export function leadPlanPrompt(scn: Scenario): string {
  return `${scenarioFacts(scn)}

Write your opening message: one or two sentences framing the approach, then a short bulleted list naming each direction (by letter) and what it tests. This is the plan you're about to fan out to sub-agents. Keep it tight.`;
}

/** Mid-run progress update once the first pilots have reported partial signal. */
export function leadProgressPrompt(scn: Scenario): string {
  const mid = scn.strategies.map((s, i) => {
    const r = s.points[Math.floor(s.points.length * 0.45)].reward;
    const trend =
      s.outcome === "fail"
        ? "stuck near baseline, not separating"
        : s.outcome === "win"
          ? "climbing fast, clear separation"
          : "climbing slowly";
    return `  ${label(i)} (${s.kind}): ~${fmt(r)} ${scn.metricName} so far — ${trend}`;
  });
  return `The pilots are partway through training (${scn.strategies[0].seeds} seeds each). Partial signal:
${mid.join("\n")}

Write a brief progress update to the human: what's separating from the ${fmt(scn.baseline)} baseline and what isn't yet. A short paragraph or a few bullets. Don't conclude — they're still running.`;
}

/** Final recommendation once every direction has reported. */
export function leadFinalPrompt(scn: Scenario): string {
  const finals = scn.strategies.map((s, i) => {
    const f = s.points[s.points.length - 1].reward;
    return `  ${label(i)} (${s.kind}): final ${fmt(f)} ${scn.metricName} — outcome ${s.outcome}`;
  });
  const w = scn.strategies[scn.winnerIdx];
  return `All directions have reported.
${finals.join("\n")}
Winner: ${label(scn.winnerIdx)} (${w.kind}), final ${fmt(w.points[w.points.length - 1].reward)} ${scn.metricName} — a clean break from the ${fmt(scn.baseline)} baseline that holds on held-out seeds (solving the task, not gaming the reward bonus).

Write your final recommendation: name the winner and why, what to promote to a full run, and what (if anything) is worth keeping as an ablation. A short paragraph or a few bullets.`;
}

/** One-paragraph summary for a finished sub-agent's card. */
export function researcherSummaryPrompt(scn: Scenario, spec: StrategySpec, i: number): string {
  const final = spec.points[spec.points.length - 1].reward;
  return `You are sub-agent ${label(i)} reporting your result up to the lead.
Direction: ${spec.kind} — ${spec.blurb}
Env: ${scn.env} · ${spec.seeds} seeds · ${spec.steps.toLocaleString()} steps
Baseline ${fmt(spec.baseline)} → final ${fmt(final)} ${scn.metricName}. Outcome: ${spec.outcome}.

Write a single tight sentence (two at most) summarizing what you found and whether it's worth scaling. Use only these numbers. No preamble.`;
}

/** Follow-up reply to a human message, grounded in the run's results. */
export function followupPrompt(scn: Scenario, userText: string): string {
  const w = scn.strategies[scn.winnerIdx];
  return `${scenarioFacts(scn)}

Results so far — winner is ${label(scn.winnerIdx)} (${w.kind}), final ${fmt(w.points[w.points.length - 1].reward)} ${scn.metricName} vs the ${fmt(scn.baseline)} baseline; the other directions stayed closer to baseline.

The human just said: "${userText}"

Reply as the lead agent — directly address what they asked, grounded in the results above. Short.`;
}

import type { EventEnvelope } from "@/lib/types";

/** One sampled point on a training curve. */
export interface CurvePoint {
  step: number;
  reward: number;
  loss: number;
  /** A 0–1 "sample-efficiency" score (reward gained per unit of budget). */
  efficiency: number;
}

export type Outcome = "win" | "climb" | "plateau" | "fail";

/** A single research direction explored by one sub-agent. */
export interface StrategySpec {
  /** Job id suffix, e.g. "a", "b" (the full job id is `${rootId}-${id}`). */
  id: string;
  /** Short kind label shown as the sub-agent's `goal` (e.g. "Curiosity (ICM)"). */
  kind: string;
  /** One-line description of what this direction tries. */
  blurb: string;
  baseline: number;
  target: number;
  steps: number;
  seeds: number;
  outcome: Outcome;
  /** Precomputed training curve (reward / loss / efficiency vs. step). */
  points: CurvePoint[];
  /** Tool calls this researcher makes (for the /view tool timeline). */
  tools: string[];
  /** Live mode: the model-written summary, cached so card + inspector agree. */
  liveSummary?: string;
}

/** The full plan derived from a goal + seed. */
export interface Scenario {
  goal: string;
  seed: number;
  env: string;
  algo: string;
  metricName: string;
  baseline: number;
  /** Lead-agent plan, as paragraphs (streamed as the first assistant turn). */
  leadPlan: string[];
  strategies: StrategySpec[];
  /** Index into `strategies` of the winning direction. */
  winnerIdx: number;
}

/** An event plus the relative time (ms from session start) it should appear. */
export interface TimedEvent {
  /** Milliseconds from session start (t=0) at which this event becomes live. */
  tMs: number;
  /** The envelope, minus the SSE `id` (assigned at stream time = array index). */
  env: Omit<EventEnvelope, "v"> & { v?: number };
}

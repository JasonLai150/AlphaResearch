import { gridworldUri, rewardPlotUri } from "@/lib/sim/artifacts";
import { label, strategySummary, workLog } from "@/lib/sim/narrative";
import { mulberry32 } from "@/lib/sim/rng";
import { assembleEvents, type MockSession } from "@/lib/sim/store";
import type { CurvePoint, StrategySpec } from "@/lib/sim/types";
import type { AgentStatus } from "@/lib/types";

/*
  Assembles the rich, per-researcher detail consumed by the /view inspector. The
  curve points and work-log are revealed up to the current wall-clock time, so a
  researcher opened mid-run shows partial progress (incremental, like the chat),
  and its live status is derived from the SAME timeline the reducer folds — so
  /view and the chat never disagree.
*/

export interface ResearcherDetail {
  sid: string;
  jobId: string;
  id: string;
  index: number;
  label: string;
  kind: string;
  blurb: string;
  status: AgentStatus;
  outcome: StrategySpec["outcome"];
  steps: number;
  seeds: number;
  baseline: number;
  target: number;
  finalReward: number | null;
  metricName: string;
  env: string;
  algo: string;
  /** Curve points revealed so far (grows over the run). */
  points: CurvePoint[];
  /** Total points in the full run (for axis scaling / progress). */
  totalPoints: number;
  tools: string[];
  workLog: string[];
  artifacts: { kind: string; url: string; caption: string }[];
  summary: string | null;
}

function suffixOf(sid: string, jobId: string): string {
  return jobId.startsWith(sid + "-") ? jobId.slice(sid.length + 1) : jobId;
}

/** Derive a researcher's live status + how many metric points have arrived. */
function liveProgress(
  s: MockSession,
  jobId: string,
  nowMs: number
): { status: AgentStatus; revealed: number; reportedFailed: boolean } {
  const offset = nowMs - s.createdAtMs;
  const events = assembleEvents(s).filter((e) => e.env.job_id === jobId && e.tMs <= offset);
  let status: AgentStatus = "pending";
  let revealed = 0;
  let reportedFailed = false;
  for (const { env } of events) {
    if (env.type === "spawn") status = status === "pending" ? "queued" : status;
    else if (env.type === "status") status = (env.payload.status as AgentStatus) ?? status;
    else if (env.type === "metric") {
      revealed += 1;
      if (status === "queued" || status === "pending") status = "running";
    } else if (env.type === "summary") {
      reportedFailed = String(env.payload.reported_status ?? "").toLowerCase() === "partial";
      status = reportedFailed ? "failed" : "done";
    }
  }
  return { status, revealed, reportedFailed };
}

export interface SessionMetrics {
  metricName: string;
  baseline: number;
  researchers: {
    id: string;
    label: string;
    kind: string;
    outcome: StrategySpec["outcome"];
    points: CurvePoint[];
  }[];
}

/** All researchers' revealed curves — drives the in-chat long-term graphs. */
export function sessionMetrics(s: MockSession, nowMs = Date.now()): SessionMetrics {
  const scn = s.scenario;
  return {
    metricName: scn.metricName,
    baseline: scn.baseline,
    researchers: scn.strategies.map((spec, i) => {
      const { revealed } = liveProgress(s, `${s.id}-${spec.id}`, nowMs);
      return {
        id: spec.id,
        label: label(i),
        kind: spec.kind,
        outcome: spec.outcome,
        points: spec.points.slice(0, Math.max(revealed, 0)),
      };
    }),
  };
}

export function researcherDetail(
  s: MockSession,
  jobId: string,
  nowMs = Date.now()
): ResearcherDetail | null {
  const scn = s.scenario;
  const id = suffixOf(s.id, jobId);
  const index = scn.strategies.findIndex((x) => x.id === id);
  if (index < 0) return null;
  const spec = scn.strategies[index];
  const { status, revealed } = liveProgress(s, jobId, nowMs);

  const points = spec.points.slice(0, Math.max(revealed, 0));
  const isDone = status === "done" || status === "failed";
  const rng = mulberry32(scn.seed ^ index);
  const allLog = workLog(scn, spec, rng);
  // Reveal work-log proportionally to training progress.
  const frac = spec.points.length > 0 ? revealed / spec.points.length : 0;
  const logCount = isDone ? allLog.length : Math.max(1, Math.round(allLog.length * frac));

  const artifacts = isDone
    ? [
        { kind: "plot", url: rewardPlotUri(spec), caption: `${spec.kind} — reward vs. steps` },
        { kind: "rollout", url: gridworldUri(spec), caption: `${scn.env} — sample rollout` },
      ]
    : [];

  return {
    sid: s.id,
    jobId,
    id,
    index,
    label: label(index),
    kind: spec.kind,
    blurb: spec.blurb,
    status,
    outcome: spec.outcome,
    steps: spec.steps,
    seeds: spec.seeds,
    baseline: spec.baseline,
    target: spec.target,
    finalReward: isDone ? spec.points[spec.points.length - 1].reward : points.at(-1)?.reward ?? null,
    metricName: scn.metricName,
    env: scn.env,
    algo: scn.algo,
    points,
    totalPoints: spec.points.length,
    tools: spec.tools,
    workLog: allLog.slice(0, logCount),
    artifacts,
    summary: isDone ? strategySummary(scn, spec, index) : null,
  };
}

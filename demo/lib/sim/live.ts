import { rewardPlotUri } from "@/lib/sim/artifacts";
import { claudeEnabled, streamProse } from "@/lib/llm/claude";
import { planningTool } from "@/lib/sim/narrative";
import {
  followupPrompt,
  LEAD_SYSTEM,
  leadFinalPrompt,
  leadPlanPrompt,
  leadProgressPrompt,
  researcherSummaryPrompt,
} from "@/lib/sim/prompts";
import { mulberry32 } from "@/lib/sim/rng";
import { jobIdFor } from "@/lib/sim/timeline";
import type { MockSession } from "@/lib/sim/store";
import type { StrategySpec, TimedEvent } from "@/lib/sim/types";

/*
  The LIVE producer: drives a session as an append-only event log written in real
  time, streaming the lead agent's prose token-by-token from a real Claude model
  while the numbers (spawns, metric curves, artifacts, winner) come from the
  deterministic scenario. Used only for newly-created interactive sessions when
  ANTHROPIC_API_KEY is set; everything else keeps the replayed template timeline.

  Each appended event is stamped tMs = now − createdAtMs, so the existing stream
  route flushes it immediately and the /view inspector (which reads the same log)
  reveals progress in lockstep with the chat.
*/

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const PACE = {
  toolGapMs: 700,
  spawnStaggerMs: 900,
  metricSpanMs: 22_000, // per-researcher training span
};

function nowOffset(s: MockSession): number {
  return Date.now() - s.createdAtMs;
}

function push(
  s: MockSession,
  jobId: string,
  depth: number,
  type: string,
  payload: Record<string, unknown>
) {
  const env: TimedEvent["env"] = {
    session_id: s.id,
    job_id: jobId,
    parent_job_id: depth === 0 ? null : jobIdFor(s.id, "root"),
    depth,
    type: type as TimedEvent["env"]["type"],
    payload,
    ts: "",
  };
  s.liveLog.push({ tMs: nowOffset(s), env });
}

/** Stream a lead-agent chat turn from Claude as live token deltas. */
async function streamLead(
  s: MockSession,
  msgId: string,
  prompt: string,
  maxTokens = 600
) {
  const rootId = jobIdFor(s.id, "root");
  const emit = (delta: string, final: boolean) =>
    push(s, rootId, 0, "token", { msg_id: msgId, delta, final, role: "assistant" });
  try {
    await streamProse({ system: LEAD_SYSTEM, prompt, maxTokens }, (d) => emit(d, false));
  } finally {
    emit("", true); // close the streaming line
  }
}

/** Drive one researcher: spawn → metric curve → artifact → Claude summary. */
async function runResearcher(s: MockSession, spec: StrategySpec, i: number, delayMs: number) {
  await sleep(delayMs);
  const jobId = jobIdFor(s.id, spec.id);
  push(s, jobId, 1, "spawn", { kind: "agent", goal: spec.kind, strategy: spec.blurb });
  await sleep(400);
  push(s, jobId, 1, "status", { status: "running" });

  const pts = spec.points;
  const stepMs = PACE.metricSpanMs / Math.max(1, pts.length - 1);
  for (let k = 0; k < pts.length; k++) {
    const pt = pts[k];
    push(s, jobId, 1, "metric", {
      step: pt.step,
      reward: pt.reward,
      series: "eval/reward",
      loss: pt.loss,
      efficiency: pt.efficiency,
    });
    await sleep(stepMs);
  }

  push(s, jobId, 1, "artifact", {
    artifact_id: `${jobId}-plot`,
    kind: "plot",
    url: rewardPlotUri(spec),
    caption: `${spec.kind} — reward vs. steps`,
  });

  // Claude writes the card summary; cache it on the spec so the /view inspector
  // (which reads strategySummary) shows the same text.
  let summary = spec.liveSummary;
  if (!summary) {
    summary = await streamProse(
      { system: LEAD_SYSTEM, prompt: researcherSummaryPrompt(s.scenario, spec, i), maxTokens: 200 }
    );
    spec.liveSummary = summary;
  }
  push(s, jobId, 1, "summary", {
    summary,
    metrics: { final_reward: pts[pts.length - 1].reward, best_reward: spec.target },
    reported_status: spec.outcome === "fail" ? "failed" : "done",
  });
}

/** Run the whole initial session live. Fire-and-forget; guarded to run once. */
export async function runLiveSession(s: MockSession) {
  if (s.producerStarted) return;
  s.producerStarted = true;
  const scn = s.scenario;
  const rng = mulberry32(scn.seed ^ 0x9e3779b9);

  push(s, jobIdFor(s.id, "root"), 0, "log", { role: "user", content: scn.goal });
  push(s, jobIdFor(s.id, "root"), 0, "status", {
    status: "running",
    backend: "modal",
    mode: "interactive",
  });

  await streamLead(s, "lead-plan", leadPlanPrompt(scn));

  for (let i = 0; i < 3; i++) {
    await sleep(PACE.toolGapMs);
    const { tool, note } = planningTool(rng);
    push(s, jobIdFor(s.id, "root"), 0, "log", { role: "tool_use", tool_name: tool, content: note });
  }

  // Fan out researchers concurrently; post a progress update partway through.
  const researchers = scn.strategies.map((spec, i) =>
    runResearcher(s, spec, i, i * PACE.spawnStaggerMs)
  );
  const progress = sleep(PACE.metricSpanMs * 0.5 + scn.strategies.length * PACE.spawnStaggerMs).then(
    () => streamLead(s, "lead-progress", leadProgressPrompt(scn))
  );

  await Promise.all([...researchers, progress]);

  await streamLead(s, "lead-final", leadFinalPrompt(scn));
  push(s, jobIdFor(s.id, "root"), 0, "status", { status: "done" });
}

/** Stream a follow-up reply to a user message into the live log. */
export async function runLiveFollowup(s: MockSession, userText: string, turnIndex: number) {
  const rootId = jobIdFor(s.id, "root");
  push(s, rootId, 0, "log", { role: "user", content: userText });
  push(s, rootId, 0, "status", { status: "running" });
  await streamLead(s, `lead-reply-${turnIndex}`, followupPrompt(s.scenario, userText), 500);
  push(s, rootId, 0, "status", { status: "done" });
}

export { claudeEnabled };

import { rewardPlotUri } from "@/lib/sim/artifacts";
import { leadFinal, leadProgress, planningTool, strategySummary } from "@/lib/sim/narrative";
import { mulberry32 } from "@/lib/sim/rng";
import type { Scenario, TimedEvent } from "@/lib/sim/types";

/*
  Composes a Scenario into the ordered, time-stamped EventEnvelope sequence for a
  single research run. Pacing lives here (as tMs offsets from session start), so
  the stream route is a dumb player. The lead agent streams into the main chat;
  sub-agents emit only spawn/status/metric/summary/artifact (no transcript spam).
*/

// Pacing knobs — tuned so a default run unfolds over ~55–75s, slow + incremental.
const PACE = {
  wordMs: 44, // per-word delay for the typewriter
  planStartMs: 500,
  toolGapMs: 900,
  spawnBaseMs: 5200,
  spawnStaggerMs: 1300,
  trainStartGapMs: 1400, // after spawn before metrics start
  trainSpanMs: 38_000, // duration over which one researcher's metrics arrive
  endPadMs: 2200,
};

interface Ctx {
  sid: string;
  rootId: string;
  events: TimedEvent[];
}

function rootEnv(c: Ctx, type: string, payload: Record<string, unknown>, tMs: number) {
  c.events.push({
    tMs,
    env: {
      session_id: c.sid,
      job_id: c.rootId,
      parent_job_id: null,
      depth: 0,
      type: type as TimedEvent["env"]["type"],
      payload,
      ts: "",
    },
  });
}

function subEnv(
  c: Ctx,
  jobId: string,
  type: string,
  payload: Record<string, unknown>,
  tMs: number
) {
  c.events.push({
    tMs,
    env: {
      session_id: c.sid,
      job_id: jobId,
      parent_job_id: c.rootId,
      depth: 1,
      type: type as TimedEvent["env"]["type"],
      payload,
      ts: "",
    },
  });
}

/** Stream `text` as word-by-word token deltas under one msg_id. Returns end tMs. */
function streamText(
  c: Ctx,
  jobId: string,
  depth: number,
  msgId: string,
  text: string,
  startMs: number,
  wordMs = PACE.wordMs
): number {
  // One token per word, trailing whitespace attached, so the reassembled text
  // matches `text` exactly while keeping the event count modest.
  const tokens = text.match(/\S+\s*/g) ?? [text];
  let t = startMs;
  tokens.forEach((tok, i) => {
    const final = i === tokens.length - 1;
    c.events.push({
      tMs: t,
      env: {
        session_id: c.sid,
        job_id: jobId,
        parent_job_id: depth === 0 ? null : c.rootId,
        depth,
        type: "token",
        payload: { msg_id: msgId, delta: tok, final },
        ts: "",
      },
    });
    t += wordMs;
  });
  return t;
}

export function jobIdFor(sid: string, suffix: string): string {
  return `${sid}-${suffix}`;
}

/** Build the full initial-run timeline (turn 0). */
export function buildRunTimeline(scn: Scenario, sid: string): TimedEvent[] {
  const rng = mulberry32(scn.seed ^ 0x9e3779b9);
  const rootId = jobIdFor(sid, "root");
  const c: Ctx = { sid, rootId, events: [] };

  // 1) The user's goal opens the conversation (so the chat reads naturally),
  //    then the lead boots and captures backend/mode for the context bar.
  rootEnv(c, "log", { role: "user", content: scn.goal }, 100);
  rootEnv(c, "status", { status: "running", backend: "modal", mode: "interactive" }, 200);

  // 2) Lead streams the plan into the main transcript.
  let t = streamText(c, rootId, 0, "lead-plan", scn.leadPlan.join("\n\n"), PACE.planStartMs);

  // 3) A couple of planning tool calls (render as "↳ used X" lines).
  for (let i = 0; i < 3; i++) {
    const { tool, note } = planningTool(rng);
    t += PACE.toolGapMs;
    rootEnv(c, "log", { role: "tool_use", tool_name: tool, content: note }, t);
  }

  // 4) Spawn each sub-agent (staggered), then drive its training curve.
  let lastTrainEnd = 0;
  scn.strategies.forEach((spec, i) => {
    const jobId = jobIdFor(sid, spec.id);
    const spawnAt = PACE.spawnBaseMs + i * PACE.spawnStaggerMs;
    subEnv(c, jobId, "spawn", { kind: "research", goal: spec.kind, strategy: spec.blurb }, spawnAt);
    subEnv(c, jobId, "status", { status: "running" }, spawnAt + 400);

    const trainStart = spawnAt + PACE.trainStartGapMs;
    const n = spec.points.length;
    spec.points.forEach((pt, k) => {
      const at = trainStart + (k / (n - 1)) * PACE.trainSpanMs;
      subEnv(
        c,
        jobId,
        "metric",
        { step: pt.step, reward: pt.reward, loss: pt.loss, efficiency: pt.efficiency },
        at
      );
    });
    const trainEnd = trainStart + PACE.trainSpanMs;

    // An artifact (plot) lands shortly before the summary.
    subEnv(
      c,
      jobId,
      "artifact",
      {
        artifact_id: `${jobId}-plot`,
        kind: "plot",
        url: rewardPlotUri(spec),
        caption: `${spec.kind} — reward vs. steps`,
      },
      trainEnd - 1500
    );

    // Summary closes the researcher (sets status done/failed + final reward).
    subEnv(
      c,
      jobId,
      "summary",
      {
        summary: strategySummary(scn, spec, i),
        metrics: { final_reward: spec.points[n - 1].reward, best_reward: spec.target },
        reported_status: spec.outcome === "fail" ? "partial" : "done",
      },
      trainEnd
    );
    lastTrainEnd = Math.max(lastTrainEnd, trainEnd);
  });

  // 5) Lead posts a progress update mid-way through training.
  const progressAt = PACE.spawnBaseMs + PACE.trainStartGapMs + PACE.trainSpanMs * 0.5;
  streamText(c, rootId, 0, "lead-progress", leadProgress(scn), progressAt);

  // 6) Lead's final recommendation, then the session closes.
  const finalStart = lastTrainEnd + PACE.endPadMs;
  const finalEnd = streamText(c, rootId, 0, "lead-final", leadFinal(scn), finalStart);
  rootEnv(c, "status", { status: "done" }, finalEnd + 300);

  c.events.sort((a, b) => a.tMs - b.tMs);
  return c.events;
}

/** Build a follow-up turn (user message + a short lead reply). */
export function buildFollowupTimeline(
  scn: Scenario,
  sid: string,
  userText: string,
  turnIndex: number,
  baseMs: number
): TimedEvent[] {
  const rootId = jobIdFor(sid, "root");
  const c: Ctx = { sid, rootId, events: [] };
  // The user's message rides the bus as a `log` (role:user) so a replay rebuilds it.
  rootEnv(c, "log", { role: "user", content: userText }, baseMs);
  rootEnv(c, "status", { status: "running" }, baseMs + 200);
  const reply = followupReply(scn, userText);
  const end = streamText(c, rootId, 0, `lead-reply-${turnIndex}`, reply, baseMs + 700);
  rootEnv(c, "status", { status: "done" }, end + 300);
  c.events.sort((a, b) => a.tMs - b.tMs);
  return c.events;
}

function followupReply(scn: Scenario, userText: string): string {
  const w = scn.strategies[scn.winnerIdx];
  const wl = String.fromCharCode(65 + scn.winnerIdx);
  if (/scale|promote|full run|production/i.test(userText)) {
    return `Promoting ${wl} (${w.kind}) to the full ${(w.steps * 4).toLocaleString()}-step run now and pinning the config. I'll stream the long-run ${scn.metricName} as it comes in.`;
  }
  if (/why|confirm|sure|verify|overfit|game|hack/i.test(userText)) {
    return `Checked — logging extrinsic-only ${scn.metricName} separately, ${wl} holds at ${(
      w.points[w.points.length - 1].reward - 0.02
    ).toFixed(2)} on pure task reward, so it's genuinely solving the task rather than gaming the bonus. The remaining failures are long detours, not skipped subgoals.`;
  }
  return `Good question. Based on the pilots, ${wl} (${w.kind}) is the most promising direction — it cleared the ${scn.baseline.toFixed(
    2
  )} plateau while the others stayed close to baseline. Want me to scale it, or run a deeper ablation first?`;
}

import { buildLoopPlan, type LoopPlan, type LoopRound, type LoopStatus, type StopReason } from "@/lib/sim/loop";
import { seedFromString } from "@/lib/sim/rng";

/*
  In-memory registry for autonomous loops (globalThis-backed, shared across
  route bundles like the session store). Each loop's rounds are revealed on a
  wall-clock so they "tick by" slowly; the stop policy is applied at the next
  round boundary after the user requests a stop.
*/

const PER_ROUND_MS = 13_000;

interface MockLoop {
  id: string;
  userId: string;
  createdAtMs: number;
  plan: LoopPlan;
  stopRequestedAtMs: number | null;
}

interface LoopState {
  loops: Map<string, MockLoop>;
  counter: number;
  seeded: boolean;
}
const g = globalThis as unknown as { __mockLoopStore?: LoopState };
const state: LoopState = (g.__mockLoopStore ??= {
  loops: new Map(),
  counter: 0,
  seeded: false,
});

export interface LiveLoop {
  id: string;
  goal: string;
  env: string;
  algo: string;
  metricName: string;
  baseline: number;
  goalMetric: number;
  maxRounds: number;
  plateauK: number;
  status: LoopStatus;
  stopReason: StopReason;
  bestMetric: number;
  createdAt: string;
  rounds: LoopRound[];
  current: { round_index: number; phase: string; progress: number } | null;
}

const PREBAKED = {
  id: "loop-doorkey",
  goal: "Maximize PPO success on MiniGrid-DoorKey-8x8 over repeated rounds",
  maxRounds: 6,
  goalMetric: 0.9,
  ageMin: 30,
};

function ensureSeeded(nowMs: number) {
  if (state.seeded) return;
  state.seeded = true;
  state.loops.set(PREBAKED.id, {
    id: PREBAKED.id,
    userId: "demo",
    createdAtMs: nowMs - PREBAKED.ageMin * 60_000,
    plan: buildLoopPlan(PREBAKED.goal, PREBAKED.maxRounds, PREBAKED.goalMetric, 2, seedFromString(PREBAKED.id)),
    stopRequestedAtMs: null,
  });
}

export function createMockLoop(
  goal: string,
  maxRounds: number,
  goalMetric: number,
  userId = "demo",
  nowMs = Date.now()
) {
  ensureSeeded(nowMs);
  state.counter += 1;
  const id = `loop-${state.counter.toString(36)}${(seedFromString(goal) % 1000).toString(36)}`;
  const seed = seedFromString(goal + ":" + state.counter);
  state.loops.set(id, {
    id,
    userId,
    createdAtMs: nowMs,
    plan: buildLoopPlan(goal, maxRounds, goalMetric, 2, seed),
    stopRequestedAtMs: null,
  });
  return { loop_id: id };
}

export function getMockLoop(lid: string, nowMs = Date.now()): MockLoop | null {
  ensureSeeded(nowMs);
  return state.loops.get(lid) ?? null;
}

export function requestStop(lid: string, nowMs = Date.now()): boolean {
  const l = state.loops.get(lid);
  if (!l) return false;
  if (l.stopRequestedAtMs == null) l.stopRequestedAtMs = nowMs;
  return true;
}

export function listMockLoops(userId: string, nowMs = Date.now()): LiveLoop[] {
  ensureSeeded(nowMs);
  return [...state.loops.values()]
    .filter((l) => l.userId === userId)
    .sort((a, b) => b.createdAtMs - a.createdAtMs)
    .map((l) => liveLoop(l, nowMs));
}

/** Derive the live loop state (revealed rounds, current round, terminal). */
export function liveLoop(l: MockLoop, nowMs = Date.now()): LiveLoop {
  const { plan } = l;
  const elapsed = nowMs - l.createdAtMs;
  const naturalDone = Math.floor(elapsed / PER_ROUND_MS); // rounds fully elapsed
  const total = plan.rounds.length;

  let revealed = Math.min(naturalDone, total);
  let status: LoopStatus = revealed >= total ? "completed" : "running";
  let stopReason: StopReason = status === "completed" ? plan.stopReason : null;

  // User stop takes effect at the next round boundary after the request — but
  // only if it was requested before the loop would have finished on its own
  // (you can't "stop" an already-completed loop).
  const naturalEndMs = l.createdAtMs + total * PER_ROUND_MS;
  if (l.stopRequestedAtMs != null && l.stopRequestedAtMs < naturalEndMs) {
    const stopRoundIdx = Math.floor((l.stopRequestedAtMs - l.createdAtMs) / PER_ROUND_MS);
    const stopBoundaryMs = l.createdAtMs + (stopRoundIdx + 1) * PER_ROUND_MS;
    const stopRevealed = Math.min(stopRoundIdx + 1, total);
    if (nowMs >= stopBoundaryMs) {
      // The in-progress round finished; the loop is now user-stopped.
      revealed = stopRevealed;
      status = "stopped";
      stopReason = "user";
    } else {
      // Stop pending: keep revealing up to the boundary, stay running.
      revealed = Math.min(revealed, stopRevealed);
      status = "running";
      stopReason = null;
    }
  }

  const rounds = plan.rounds.slice(0, revealed);
  const bestMetric = rounds.length ? rounds[rounds.length - 1].best_metric : plan.baseline;

  let current: LiveLoop["current"] = null;
  if (status === "running" && revealed < total) {
    const intra = (elapsed % PER_ROUND_MS) / PER_ROUND_MS;
    const phase = intra < 0.3 ? "planning" : intra < 0.7 ? "dispatching" : "synthesizing";
    current = { round_index: revealed, phase, progress: intra };
  }

  return {
    id: l.id,
    goal: plan.goal,
    env: plan.env,
    algo: plan.algo,
    metricName: plan.metricName,
    baseline: plan.baseline,
    goalMetric: plan.goalMetric,
    maxRounds: plan.maxRounds,
    plateauK: plan.plateauK,
    status,
    stopReason,
    bestMetric,
    createdAt: new Date(l.createdAtMs).toISOString(),
    rounds,
    current,
  };
}

import { buildScenario } from "@/lib/sim/scenario";
import { seedFromString } from "@/lib/sim/rng";
import {
  buildFollowupTimeline,
  buildRunTimeline,
  jobIdFor,
} from "@/lib/sim/timeline";
import type { Scenario, TimedEvent } from "@/lib/sim/types";
import type { WireSession } from "@/lib/types";

/*
  In-memory session registry shared across the /api/mock route handlers (one
  instance per server process — sufficient for a demo; nothing is persisted).
  Holds each session's scenario + seed and assembles the wall-clock event
  timeline (initial run + any follow-up turns) on demand, cached by turn count.
*/

interface Turn {
  userText: string;
  baseMs: number; // offset from session start at which this turn schedules
}

export interface MockSession {
  id: string;
  userId: string;
  goal: string;
  mode: string;
  createdAtMs: number;
  scenario: Scenario;
  turns: Turn[];
  cache: { turnCount: number; events: TimedEvent[] } | null;
}

/*
  Next.js compiles each route handler into its own module bundle, so a plain
  module-level Map would NOT be shared across /sessions, /stream, /full, etc.
  Stash the registry on globalThis (one per Node process) so every route sees
  the same sessions.
*/
interface StoreState {
  sessions: Map<string, MockSession>;
  counter: number;
  seeded: boolean;
}
const g = globalThis as unknown as { __mockStore?: StoreState };
const state: StoreState = (g.__mockStore ??= {
  sessions: new Map<string, MockSession>(),
  counter: 0,
  seeded: false,
});
const sessions = state.sessions;

const PREBAKED: { id: string; goal: string; ageMin: number }[] = [
  { id: "demo-doorkey", goal: "Improve PPO sample efficiency on MiniGrid-DoorKey-8x8. We're plateauing around 0.55 success after 2M steps.", ageMin: 4 },
  { id: "demo-shaping", goal: "Reward shaping ablations for sparse-reward navigation", ageMin: 62 },
  { id: "demo-entropy", goal: "Entropy coefficient sweep for PPO exploration", ageMin: 180 },
  { id: "demo-icm", goal: "Curiosity-driven exploration (ICM) on MiniGrid-MultiRoom", ageMin: 1500 },
  { id: "demo-sac", goal: "SAC vs PPO baseline on MuJoCo-HalfCheetah-v4 mean return", ageMin: 2900 },
];

/** Seed a handful of finished "history" sessions so the sidebar isn't empty. */
function ensureSeeded(nowMs: number) {
  if (state.seeded) return;
  state.seeded = true;
  for (const p of PREBAKED) {
    const createdAtMs = nowMs - p.ageMin * 60_000;
    const seed = seedFromString(p.id + p.goal);
    sessions.set(p.id, {
      id: p.id,
      userId: "demo",
      goal: p.goal,
      mode: "interactive",
      createdAtMs,
      scenario: buildScenario(p.goal, seed),
      turns: [],
      cache: null,
    });
  }
}

export function createMockSession(goal: string, userId = "demo", nowMs = Date.now()) {
  ensureSeeded(nowMs);
  state.counter += 1;
  const counter = state.counter;
  const id = `s${counter.toString(36)}${(seedFromString(goal) % 1000).toString(36)}`;
  const seed = seedFromString(goal + ":" + counter);
  sessions.set(id, {
    id,
    userId,
    goal,
    mode: "interactive",
    createdAtMs: nowMs,
    scenario: buildScenario(goal, seed),
    turns: [],
    cache: null,
  });
  return { session_id: id, root_job_id: jobIdFor(id, "root") };
}

export function getMockSession(sid: string, nowMs = Date.now()): MockSession | null {
  ensureSeeded(nowMs);
  return sessions.get(sid) ?? null;
}

export function listMockSessions(userId: string, nowMs = Date.now()): WireSession[] {
  ensureSeeded(nowMs);
  return [...sessions.values()]
    .filter((s) => s.userId === userId)
    .sort((a, b) => b.createdAtMs - a.createdAtMs)
    .map((s) => toWire(s, nowMs));
}

/** Append a follow-up user turn; schedules it "now" relative to session start. */
export function addTurn(sid: string, userText: string, nowMs = Date.now()): boolean {
  const s = sessions.get(sid);
  if (!s || !userText.trim()) return false;
  const events = assembleEvents(s);
  const lastT = events.length ? events[events.length - 1].tMs : 0;
  const nowOffset = nowMs - s.createdAtMs;
  const baseMs = Math.max(lastT + 800, nowOffset);
  s.turns.push({ userText: userText.trim(), baseMs });
  s.cache = null;
  return true;
}

/** The full assembled timeline (initial run + follow-up turns). Cached. */
export function assembleEvents(s: MockSession): TimedEvent[] {
  if (s.cache && s.cache.turnCount === s.turns.length) return s.cache.events;
  const events = buildRunTimeline(s.scenario, s.id);
  s.turns.forEach((turn, i) => {
    events.push(...buildFollowupTimeline(s.scenario, s.id, turn.userText, i + 1, turn.baseMs));
  });
  events.sort((a, b) => a.tMs - b.tMs);
  s.cache = { turnCount: s.turns.length, events };
  return events;
}

/** True once the latest event's scheduled time has passed (run is terminal). */
export function isTerminal(s: MockSession, nowMs = Date.now()): boolean {
  const events = assembleEvents(s);
  const lastT = events.length ? events[events.length - 1].tMs : 0;
  return nowMs - s.createdAtMs > lastT;
}

function toWire(s: MockSession, nowMs: number): WireSession {
  return {
    id: s.id,
    user_id: s.userId,
    goal: s.goal,
    mode: s.mode,
    status: isTerminal(s, nowMs) ? "done" : "running",
    created_at: new Date(s.createdAtMs).toISOString(),
    root_job_id: jobIdFor(s.id, "root"),
  };
}

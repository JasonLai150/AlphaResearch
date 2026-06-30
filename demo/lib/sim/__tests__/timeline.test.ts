import { describe, expect, it } from "vitest";

import { buildScenario } from "@/lib/sim/scenario";
import { buildRunTimeline } from "@/lib/sim/timeline";
import {
  applyEvent,
  emptyState,
  graphOf,
  rootJob,
  subagentsOf,
  treeOf,
} from "@/lib/session-reducer";
import type { SessionState } from "@/lib/types";

/** Fold an entire timeline through the REAL reducer (ignoring pacing). */
function fold(goal: string, seed: number): SessionState {
  const sid = "test-sid";
  const scn = buildScenario(goal, seed);
  const events = buildRunTimeline(scn, sid);
  let state = emptyState(sid, goal);
  for (const { env } of events) state = applyEvent(state, { ...env, v: 1 });
  return state;
}

describe("simulation engine → reducer", () => {
  it("rebuilds a coherent terminal session from the generated stream", () => {
    const scn = buildScenario("Improve PPO sample efficiency on DoorKey", 12345);
    const state = fold(scn.goal, 12345);

    // Root (lead) exists, is done, and is the tree root.
    const root = rootJob(state);
    expect(root).toBeTruthy();
    expect(root!.status).toBe("done");

    // One sub-agent per strategy, all terminal with a final reward.
    const subs = subagentsOf(state);
    expect(subs.length).toBe(scn.strategies.length);
    for (const s of subs) {
      expect(["done", "failed"]).toContain(s.status);
      expect(typeof s.reward).toBe("number");
      expect(s.rewards!.length).toBeGreaterThan(5);
    }

    // The transcript carries the lead's streamed turns (assistant), no orphans.
    const assistant = state.transcript.filter((t) => t.role === "assistant");
    expect(assistant.length).toBeGreaterThanOrEqual(3);
    expect(assistant.every((t) => t.streaming === false)).toBe(true);

    // Graph: root + one node per sub-agent, edges root→each.
    const graph = graphOf(state);
    expect(graph.nodes.length).toBe(scn.strategies.length + 1);
    expect(graph.links.length).toBe(scn.strategies.length);

    // Tree root labelled "Main agent".
    expect(treeOf(state)!.label).toBe("Main agent");
  });

  it("is deterministic: same seed → identical timeline", () => {
    const a = buildRunTimeline(buildScenario("goal X", 7), "sid");
    const b = buildRunTimeline(buildScenario("goal X", 7), "sid");
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });

  it("varies with the seed", () => {
    const a = buildRunTimeline(buildScenario("goal X", 7), "sid");
    const b = buildRunTimeline(buildScenario("goal X", 99), "sid");
    expect(JSON.stringify(a)).not.toBe(JSON.stringify(b));
  });

  it("token deltas reassemble to the exact lead plan text", () => {
    const scn = buildScenario("goal Y", 42);
    const events = buildRunTimeline(scn, "sid");
    const planDeltas = events
      .filter((e) => e.env.type === "token" && e.env.payload.msg_id === "lead-plan")
      .map((e) => e.env.payload.delta as string)
      .join("");
    expect(planDeltas).toBe(scn.leadPlan.join("\n\n"));
  });

  it("the winner ends with the highest final reward (across many seeds)", () => {
    // The recommendation must never contradict the numbers, for ANY seed.
    for (let seed = 1; seed <= 200; seed++) {
      const scn = buildScenario("Improve PPO sample efficiency on DoorKey", seed);
      const finals = scn.strategies.map((s) => s.points[s.points.length - 1].reward);
      const max = Math.max(...finals);
      expect(finals[scn.winnerIdx]).toBe(max);
    }
  });

  it("curves start at the stated baseline", () => {
    const scn = buildScenario("Improve PPO on DoorKey", 314);
    for (const s of scn.strategies) {
      expect(Math.abs(s.points[0].reward - scn.baseline)).toBeLessThan(0.05);
    }
  });
});

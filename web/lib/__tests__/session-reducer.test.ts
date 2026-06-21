import { describe, it, expect } from "vitest";
import {
  emptyState,
  applyEvent,
  subagentsOf,
  treeOf,
  artifactsOf,
} from "@/lib/session-reducer";
import type { EventEnvelope, SessionState } from "@/lib/types";

/*
  Tests for the event-stream reducer that folds the SSE bus into live view
  state. Covers role mapping, JobView assembly, idempotent metric upserts,
  deterministic replay, tree building, summary terminal status, the error
  event, and the selectors.
*/

// ─── Helpers ─────────────────────────────────────────────────────────────────

const SESSION = "sess-1";

function env(over: Partial<EventEnvelope> & Pick<EventEnvelope, "type">): EventEnvelope {
  return {
    session_id: SESSION,
    job_id: "",
    parent_job_id: null,
    depth: 0,
    payload: {},
    ts: "2026-06-21T00:00:00Z",
    v: 1,
    ...over,
  };
}

function reduce(events: EventEnvelope[], init?: SessionState): SessionState {
  return events.reduce(applyEvent, init ?? emptyState(SESSION));
}

// ─── (a) log event → transcript item with correct role mapping ───────────────

describe("log events → transcript role mapping", () => {
  it("maps user/system through, tool_use→tool, and others→assistant", () => {
    const events: EventEnvelope[] = [
      env({ type: "log", payload: { role: "user", content: "hi" } }),
      env({ type: "log", payload: { role: "system", content: "boot" } }),
      env({
        type: "log",
        payload: { role: "tool_use", content: "call", tool_name: "Bash" },
      }),
      env({ type: "log", payload: { role: "tool_result", content: "out" } }),
      env({ type: "log", payload: { role: "assistant", content: "thinking" } }),
      // Unknown role falls back to assistant.
      env({ type: "log", payload: { role: "weird", content: "?" } }),
    ];

    const state = reduce(events);
    expect(state.transcript.map((t) => t.role)).toEqual([
      "user",
      "system",
      "tool",
      "tool",
      "assistant",
      "assistant",
    ]);
    // Content and tool name are carried through.
    expect(state.transcript[0].text).toBe("hi");
    expect(state.transcript[2].toolName).toBe("Bash");
    expect(state.transcript[3].toolName).toBeUndefined();
    // Ids derive from the monotonic seq, not the array index.
    expect(state.transcript.map((t) => t.id)).toEqual([
      "t0",
      "t1",
      "t2",
      "t3",
      "t4",
      "t5",
    ]);
    expect(state.seq).toBe(6);
  });
});

// ─── (b) spawn then metric builds a JobView with sorted rewards ──────────────

describe("spawn then metric → JobView with sorted rewards", () => {
  it("creates the job from spawn and accumulates sorted reward points", () => {
    const events: EventEnvelope[] = [
      env({
        type: "spawn",
        job_id: "j1",
        payload: { kind: "experiment", goal: "tune lr", strategy: "ppo" },
      }),
      // Arrive out of order to prove the reducer sorts by step.
      env({ type: "metric", job_id: "j1", payload: { step: 2, reward: 0.4 } }),
      env({ type: "metric", job_id: "j1", payload: { step: 0, reward: 0.1 } }),
      env({ type: "metric", job_id: "j1", payload: { step: 1, reward: 0.25 } }),
    ];

    const state = reduce(events);
    const job = state.jobs["j1"];
    expect(job).toBeDefined();
    expect(job.kind).toBe("experiment");
    expect(job.goal).toBe("tune lr");
    expect(job.strategy).toBe("ppo");
    // metric flips the job to running.
    expect(job.status).toBe("running");
    // Rewards are sorted by step regardless of arrival order.
    expect(job.rewards).toEqual([
      { step: 0, reward: 0.1 },
      { step: 1, reward: 0.25 },
      { step: 2, reward: 0.4 },
    ]);
    // lastReward tracks the most recently applied metric value.
    expect(job.lastReward).toBe(0.25);
    // Spawn registers the job in order and (depth 0) as root.
    expect(state.order).toEqual(["j1"]);
    expect(state.rootId).toBe("j1");
  });
});

// ─── (c) metric upsert is idempotent + full replay is deterministic ──────────

describe("metric upsert idempotency and deterministic replay", () => {
  it("re-applying the same step overwrites in place (one point, not two)", () => {
    const events: EventEnvelope[] = [
      env({ type: "spawn", job_id: "j1", payload: {} }),
      env({ type: "metric", job_id: "j1", payload: { step: 3, reward: 0.5 } }),
      // Same step again with a new value: upsert, not append.
      env({ type: "metric", job_id: "j1", payload: { step: 3, reward: 0.9 } }),
    ];
    const state = reduce(events);
    expect(state.jobs["j1"].rewards).toEqual([{ step: 3, reward: 0.9 }]);
  });

  it("replaying the full event list twice yields identical state", () => {
    const events: EventEnvelope[] = [
      env({ type: "log", payload: { role: "user", content: "go" } }),
      env({
        type: "spawn",
        job_id: "j1",
        parent_job_id: null,
        depth: 0,
        payload: { kind: "agent", goal: "root" },
      }),
      env({
        type: "spawn",
        job_id: "j2",
        parent_job_id: "j1",
        depth: 1,
        payload: { kind: "experiment", goal: "child" },
      }),
      env({ type: "metric", job_id: "j2", payload: { step: 0, reward: 0.2 } }),
      env({ type: "metric", job_id: "j2", payload: { step: 1, reward: 0.6 } }),
      // Replaying the metric for step 0 (e.g. on reconnect) must be a no-op.
      env({ type: "metric", job_id: "j2", payload: { step: 0, reward: 0.2 } }),
      env({ type: "artifact", job_id: "j2", payload: { artifact_id: "a1", kind: "plot", url: "u" } }),
      env({ type: "summary", job_id: "j2", payload: { summary: "done", reported_status: "done" } }),
    ];

    const once = reduce(events);
    const twice = reduce(events);
    // Deterministic: replaying the same stream rebuilds byte-identical state.
    expect(twice).toEqual(once);
  });
});

// ─── (d) depth-0 root + depth-1 child → 2-level tree via treeOf ──────────────

describe("treeOf builds a 2-level tree from root + child", () => {
  it("nests a depth-1 child under the depth-0 root", () => {
    const events: EventEnvelope[] = [
      env({
        type: "spawn",
        job_id: "root",
        parent_job_id: null,
        depth: 0,
        payload: { kind: "agent" },
      }),
      env({
        type: "spawn",
        job_id: "child",
        parent_job_id: "root",
        depth: 1,
        payload: { kind: "experiment" },
      }),
      env({ type: "status", job_id: "child", payload: { status: "running" } }),
    ];

    const tree = treeOf(reduce(events));
    expect(tree).not.toBeNull();
    expect(tree!.id).toBe("root");
    expect(tree!.label).toBe("Main agent");
    expect(tree!.children).toHaveLength(1);
    const child = tree!.children![0];
    expect(child.id).toBe("child");
    // First child of the depth-0 root is labeled "A".
    expect(child.label).toBe("A");
    expect(child.status).toBe("running");
    expect(child.children).toEqual([]);
  });
});

// ─── (e) summary sets terminal status done/failed ────────────────────────────

describe("summary sets terminal status", () => {
  it("sets done by default and reads final_reward into lastReward", () => {
    const events: EventEnvelope[] = [
      env({ type: "spawn", job_id: "j1", payload: {} }),
      env({
        type: "summary",
        job_id: "j1",
        payload: { summary: "all good", metrics: { final_reward: 0.77 } },
      }),
    ];
    const job = reduce(events).jobs["j1"];
    expect(job.status).toBe("done");
    expect(job.summary).toBe("all good");
    expect(job.lastReward).toBe(0.77);
  });

  it("sets failed when reported_status is failed", () => {
    const events: EventEnvelope[] = [
      env({ type: "spawn", job_id: "j1", payload: {} }),
      env({ type: "summary", job_id: "j1", payload: { reported_status: "failed" } }),
    ];
    expect(reduce(events).jobs["j1"].status).toBe("failed");
  });
});

// ─── (f) error event appends a system transcript item ────────────────────────

describe("error event → system transcript item", () => {
  it("appends a system line using the reason", () => {
    const state = reduce([
      env({ type: "error", payload: { reason: "boom" } }),
    ]);
    expect(state.transcript).toHaveLength(1);
    expect(state.transcript[0].role).toBe("system");
    expect(state.transcript[0].text).toBe("boom");
  });

  it("falls back through message → default text", () => {
    const fromMessage = reduce([env({ type: "error", payload: { message: "oops" } })]);
    expect(fromMessage.transcript[0].text).toBe("oops");

    const fromDefault = reduce([env({ type: "error", payload: {} })]);
    expect(fromDefault.transcript[0].role).toBe("system");
    expect(fromDefault.transcript[0].text).toBe("agent error");
  });
});

// ─── (g) selectors subagentsOf / artifactsOf ─────────────────────────────────

describe("selectors", () => {
  function rootWithTwoChildren(): SessionState {
    return reduce([
      env({ type: "spawn", job_id: "root", parent_job_id: null, depth: 0, payload: {} }),
      env({
        type: "spawn",
        job_id: "c1",
        parent_job_id: "root",
        depth: 1,
        payload: { kind: "experiment", goal: "Alpha run" },
      }),
      env({ type: "metric", job_id: "c1", payload: { step: 0, reward: 0.3 } }),
      env({
        type: "spawn",
        job_id: "c2",
        parent_job_id: "root",
        depth: 1,
        payload: { kind: "experiment" },
      }),
      env({ type: "artifact", job_id: "root", payload: { artifact_id: "a0", kind: "log", url: "u0" } }),
      env({ type: "artifact", job_id: "c1", payload: { artifact_id: "a1", kind: "plot", url: "u1" } }),
    ]);
  }

  it("subagentsOf lists the root's children with stable A/B labels and rewards", () => {
    const subs = subagentsOf(rootWithTwoChildren());
    expect(subs.map((s) => s.id)).toEqual(["c1", "c2"]);
    expect(subs.map((s) => s.name)).toEqual(["A", "B"]);
    // c1 has a goal → used as kind; carries its reward and reward curve.
    expect(subs[0].kind).toBe("Alpha run");
    expect(subs[0].reward).toBe(0.3);
    expect(subs[0].rewards).toEqual([{ step: 0, reward: 0.3 }]);
    // c2 has no goal and no reward yet → note describes its state.
    expect(subs[1].reward).toBeUndefined();
    expect(subs[1].note).toBeDefined();
  });

  it("artifactsOf flattens every job's artifacts in job order", () => {
    const arts = artifactsOf(rootWithTwoChildren());
    expect(arts.map((a) => a.id)).toEqual(["a0", "a1"]);
    expect(arts[0].job_id).toBe("root");
    expect(arts[1].job_id).toBe("c1");
    expect(arts[1].kind).toBe("plot");
  });

  it("subagentsOf returns [] when there is no root", () => {
    expect(subagentsOf(emptyState(SESSION))).toEqual([]);
  });
});

// ─── (h) token events coalesce into one streaming assistant item ─────────────

describe("token events → coalesced typewriter transcript item", () => {
  it("grows one assistant item by msg_id and clears streaming on final", () => {
    const events: EventEnvelope[] = [
      env({ type: "token", job_id: "root", payload: { msg_id: "m1#0", role: "assistant", delta: "Hel", final: false } }),
      env({ type: "token", job_id: "root", payload: { msg_id: "m1#0", role: "assistant", delta: "lo ", final: false } }),
      env({ type: "token", job_id: "root", payload: { msg_id: "m1#0", role: "assistant", delta: "world", final: true } }),
    ];
    const state = reduce(events);
    // One transcript item, not three; full text assembled; no phantom job.
    expect(state.transcript).toHaveLength(1);
    expect(state.transcript[0].role).toBe("assistant");
    expect(state.transcript[0].text).toBe("Hello world");
    expect(state.transcript[0].streaming).toBe(false);
    expect(state.transcript[0].msgId).toBe("m1#0");
    expect(state.order).toEqual([]); // token events never create jobs
  });

  it("keeps streaming true while deltas are mid-flight", () => {
    const state = reduce([
      env({ type: "token", job_id: "root", payload: { msg_id: "m2#0", role: "assistant", delta: "typing", final: false } }),
    ]);
    expect(state.transcript[0].streaming).toBe(true);
  });

  it("separates distinct msg_ids into distinct items", () => {
    const state = reduce([
      env({ type: "token", job_id: "root", payload: { msg_id: "m1#0", delta: "a", final: true } }),
      env({ type: "token", job_id: "root", payload: { msg_id: "m2#0", delta: "b", final: true } }),
    ]);
    expect(state.transcript.map((t) => t.text)).toEqual(["a", "b"]);
    expect(state.transcript.map((t) => t.id)).toEqual(["t0", "t1"]);
  });

  it("replaying the full token stream yields identical state (idempotent)", () => {
    const events: EventEnvelope[] = [
      env({ type: "token", job_id: "root", payload: { msg_id: "m1#0", delta: "one ", final: false } }),
      env({ type: "token", job_id: "root", payload: { msg_id: "m1#0", delta: "two", final: true } }),
    ];
    expect(reduce(events)).toEqual(reduce(events));
  });
});

// ─── autonomous loop: round_started / loop_stopped → state.loop ──────────────

describe("autonomous loop lifecycle", () => {
  const stream: EventEnvelope[] = [
    env({
      type: "status",
      job_id: "r1",
      payload: { phase: "round_started", round_index: 1, max_rounds: 3, goal_metric: 0.9 },
    }),
    env({ type: "metric", job_id: "r1", payload: { step: 10, reward: 0.6 } }),
    env({
      type: "summary",
      job_id: "r1",
      payload: { summary: "round 1", metrics: { best_reward: 0.6 } },
    }),
    env({
      type: "status",
      job_id: "r2",
      payload: { phase: "round_started", round_index: 2, max_rounds: 3, goal_metric: 0.9 },
    }),
    env({
      type: "status",
      job_id: "r2",
      payload: {
        phase: "loop_stopped",
        status: "completed",
        reason: "reached max_rounds=3",
        round_index: 3,
        max_rounds: 3,
        goal_metric: 0.9,
      },
    }),
  ];

  it("tracks round progress and terminal status", () => {
    const state = reduce(stream);
    expect(state.loop).toEqual({
      round: 3,
      maxRounds: 3,
      goalMetric: 0.9,
      status: "completed",
      reason: "reached max_rounds=3",
    });
  });

  it("shows round 1 / 3 while running", () => {
    const state = reduce(stream.slice(0, 3));
    expect(state.loop).toMatchObject({ round: 1, maxRounds: 3, status: "running" });
  });

  it("a round_started event does not create a phantom job node", () => {
    const state = reduce([stream[0]]);
    expect(state.order).toEqual([]);
    expect(state.rootId).toBeNull();
  });

  it("is idempotent under full replay", () => {
    expect(reduce(stream)).toEqual(reduce(stream));
  });

  it("oneshot sessions never populate loop", () => {
    const state = reduce([
      env({ type: "status", job_id: "root", payload: { status: "running" } }),
      env({ type: "summary", job_id: "root", payload: { summary: "done" } }),
    ]);
    expect(state.loop).toBeUndefined();
  });
});

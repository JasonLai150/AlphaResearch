import { describe, expect, it } from "vitest";

import {
  groupByMode,
  recent,
  summarize,
  toAgentStatus,
} from "@/lib/session-stats";
import type { WireSession } from "@/lib/types";

function mk(partial: Partial<WireSession>): WireSession {
  return {
    id: partial.id ?? "s",
    user_id: "u",
    goal: partial.goal ?? "goal",
    mode: partial.mode ?? "default",
    status: partial.status ?? "pending",
    created_at: partial.created_at ?? "2026-06-21T08:00:00Z",
    root_job_id: null,
  };
}

describe("toAgentStatus", () => {
  it("passes through the canonical statuses", () => {
    expect(toAgentStatus("running")).toBe("running");
    expect(toAgentStatus("done")).toBe("done");
    expect(toAgentStatus("failed")).toBe("failed");
    expect(toAgentStatus("cancelled")).toBe("cancelled");
  });

  it("is case-insensitive and maps common synonyms", () => {
    expect(toAgentStatus("COMPLETED")).toBe("done");
    expect(toAgentStatus("Succeeded")).toBe("done");
    expect(toAgentStatus("error")).toBe("failed");
    expect(toAgentStatus("canceled")).toBe("cancelled");
  });

  it("defaults unknown statuses to pending", () => {
    expect(toAgentStatus("wat")).toBe("pending");
    expect(toAgentStatus("")).toBe("pending");
  });
});

describe("summarize", () => {
  it("buckets sessions into total/running/done/failed", () => {
    const s = summarize([
      mk({ status: "running" }),
      mk({ status: "done" }),
      mk({ status: "failed" }),
      mk({ status: "pending" }),
      mk({ status: "completed" }),
      mk({ status: "cancelled" }),
    ]);
    expect(s.total).toBe(6);
    expect(s.running).toBe(2); // running + pending (in-flight)
    expect(s.done).toBe(2); // done + completed
    expect(s.failed).toBe(1);
  });

  it("returns zeros for an empty list", () => {
    expect(summarize([])).toEqual({
      total: 0,
      running: 0,
      done: 0,
      failed: 0,
    });
  });
});

describe("recent", () => {
  it("returns the n newest sessions by created_at, descending", () => {
    const sessions = [
      mk({ id: "old", created_at: "2026-06-20T08:00:00Z" }),
      mk({ id: "new", created_at: "2026-06-21T12:00:00Z" }),
      mk({ id: "mid", created_at: "2026-06-21T08:00:00Z" }),
    ];
    expect(recent(sessions, 2).map((s) => s.id)).toEqual(["new", "mid"]);
  });

  it("does not mutate the input array", () => {
    const sessions = [
      mk({ id: "a", created_at: "2026-06-20T08:00:00Z" }),
      mk({ id: "b", created_at: "2026-06-21T08:00:00Z" }),
    ];
    recent(sessions, 1);
    expect(sessions.map((s) => s.id)).toEqual(["a", "b"]);
  });
});

describe("groupByMode", () => {
  it("groups sessions by mode, newest group first", () => {
    const groups = groupByMode([
      mk({ id: "a", mode: "ppo", created_at: "2026-06-21T08:00:00Z" }),
      mk({ id: "b", mode: "sac", created_at: "2026-06-21T10:00:00Z" }),
      mk({ id: "c", mode: "ppo", created_at: "2026-06-21T12:00:00Z" }),
    ]);
    // sac's newest is 10:00; ppo's newest is 12:00 → ppo group first.
    expect(groups.map((g) => g.mode)).toEqual(["ppo", "sac"]);
    expect(groups[0].sessions.map((s) => s.id)).toEqual(["c", "a"]);
  });

  it("falls back to 'default' for an empty mode", () => {
    const groups = groupByMode([mk({ id: "a", mode: "" })]);
    expect(groups[0].mode).toBe("default");
  });
});

import type { AgentStatus, WireSession } from "@/lib/types";

// Backend session.status is a free-form string; normalize it to the AgentStatus
// union the UI primitives (StatusDot) understand. Unknown values fall back to
// "pending" so a new/unrecognized state still renders as in-flight.
const SYNONYMS: Record<string, AgentStatus> = {
  running: "running",
  pending: "pending",
  queued: "queued",
  done: "done",
  completed: "done",
  complete: "done",
  succeeded: "done",
  success: "done",
  failed: "failed",
  error: "failed",
  errored: "failed",
  cancelled: "cancelled",
  canceled: "cancelled",
  stopped: "cancelled",
};

export function toAgentStatus(status: string): AgentStatus {
  return SYNONYMS[status.trim().toLowerCase()] ?? "pending";
}

export interface SessionSummary {
  total: number;
  running: number;
  done: number;
  failed: number;
}

/** Count sessions into the dashboard's four buckets. */
export function summarize(sessions: WireSession[]): SessionSummary {
  const s: SessionSummary = {
    total: sessions.length,
    running: 0,
    done: 0,
    failed: 0,
  };
  for (const sess of sessions) {
    const st = toAgentStatus(sess.status);
    if (st === "running" || st === "pending" || st === "queued") s.running++;
    else if (st === "done") s.done++;
    else if (st === "failed") s.failed++;
  }
  return s;
}

const byCreatedDesc = (a: WireSession, b: WireSession) =>
  +new Date(b.created_at) - +new Date(a.created_at);

/** The n newest sessions by created_at, descending. Does not mutate input. */
export function recent(sessions: WireSession[], n: number): WireSession[] {
  return [...sessions].sort(byCreatedDesc).slice(0, n);
}

export interface ModeGroup {
  mode: string;
  sessions: WireSession[];
}

/**
 * Group sessions by `mode` (the only natural grouping field). Sessions within a
 * group and the groups themselves are ordered newest-first.
 */
export function groupByMode(sessions: WireSession[]): ModeGroup[] {
  const map = new Map<string, WireSession[]>();
  for (const s of sessions) {
    const mode = s.mode || "default";
    (map.get(mode) ?? map.set(mode, []).get(mode)!).push(s);
  }
  const groups: ModeGroup[] = [...map.entries()].map(([mode, arr]) => ({
    mode,
    sessions: [...arr].sort(byCreatedDesc),
  }));
  groups.sort(
    (a, b) =>
      +new Date(b.sessions[0].created_at) - +new Date(a.sessions[0].created_at)
  );
  return groups;
}

// Mirror of infra/schemas.py EventEnvelope — the SSE contract.
export type EventType =
  | "log"
  | "metric"
  | "status"
  | "spawn"
  | "artifact"
  | "summary";

export interface EventEnvelope {
  session_id: string;
  job_id: string;
  parent_job_id: string | null;
  depth: number;
  type: EventType;
  payload: Record<string, any>;
  ts: string;
  v: number;
}

export interface JobNode {
  jobId: string;
  parentJobId: string | null;
  depth: number;
  status: string;
  kind?: string;
  goal?: string;
  lastReward?: number;
  rewards: { step: number; reward: number }[];
  summary?: string;
  artifacts: { url: string; caption?: string }[];
  logs: string[];
}

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

// ─── Dashboard view models ──────────────────────────────────────────────────
// Presentation-layer types for the Overview dashboard. These stay decoupled
// from the wire types above so the SSE stream can be mapped onto them later.

export type AgentStatus = "running" | "queued" | "done" | "failed" | "pending";

export interface ChatSummary {
  id: string;
  title: string;
  /** Human-relative timestamp, e.g. "2m ago". */
  updatedAt: string;
}

export type MessageRole = "user" | "agent";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  author: string;
  /** Paragraphs of message text. */
  blocks: string[];
  /** Inline run status, e.g. "Ran 4 tools · spawning subagents". */
  activity?: { label: string; status: AgentStatus };
}

/** The execution context chips above the transcript (Local · repo · branch · worktree). */
export interface RepoContext {
  env: string;
  repo: string;
  branch: string;
  worktree: string;
}

/** A node in the agent tree visualization. */
export interface TreeNode {
  id: string;
  label: string;
  status: AgentStatus;
  children?: TreeNode[];
}

export interface Subagent {
  id: string;
  name: string;
  /** e.g. "Research". */
  kind: string;
  status: AgentStatus;
  reward?: number;
  /** Shown when no reward is available yet (e.g. "queued"). */
  note?: string;
}

export interface CurrentUser {
  name: string;
  handle: string;
  role: string;
  initials: string;
}

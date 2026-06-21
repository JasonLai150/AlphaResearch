// Mirror of infra/schemas.py EventEnvelope — the SSE contract.
export type EventType =
  | "log"
  | "metric"
  | "status"
  | "spawn"
  | "artifact"
  | "summary"
  | "error"
  | "token";

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

export type AgentStatus =
  | "running"
  | "queued"
  | "done"
  | "failed"
  | "pending"
  | "cancelled";

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
  /** Reward curve for the inline sparkline. */
  rewards?: MetricPoint[];
}

export interface CurrentUser {
  name: string;
  handle: string;
  role: string;
  initials: string;
}

// ─── Wire types (mirror infra/schemas.py) ────────────────────────────────────

export interface WireSession {
  id: string;
  user_id: string;
  goal: string;
  mode: string;
  status: string;
  created_at: string;
  root_job_id?: string | null;
}

export interface WireJob {
  id: string;
  session_id: string;
  parent_job_id: string | null;
  depth: number;
  kind: string;
  status: string;
  params: Record<string, any>;
  backend: string;
  sandbox_id: string | null;
  created_at: string;
}

export interface WireRun {
  job_id: string;
  status: string;
  summary: string;
  metrics: Record<string, any>;
  created_at: string;
}

export interface WireArtifact {
  id: string;
  job_id: string;
  kind: string;
  url: string;
  caption: string | null;
  bytes: number;
}

export interface WireMessage {
  session_id: string;
  job_id: string;
  role: string;
  content: string;
  tool_name: string | null;
  tool_input: Record<string, any> | null;
  ts: string;
}

/** Autonomous loop snapshot from read_full_session (mirrors infra/schemas.py Loop). */
export interface WireLoop {
  session_id: string;
  status: LoopStatus;
  max_rounds: number;
  goal_metric: number | null;
  plateau_k: number;
  stop_requested: boolean;
  current_job_id: string | null;
  stop_reason: string;
  rounds: { round_index: number; best_metric: number | null }[];
}

export interface FullSession {
  session: WireSession | null;
  jobs: WireJob[];
  runs: WireRun[];
  tree: Record<string, string[]>;
  transcript: WireMessage[];
  artifacts: WireArtifact[];
  /** Null for oneshot sessions. */
  loop?: WireLoop | null;
}

// ─── Live view models (built by the reducer from the event stream) ───────────

export interface MetricPoint {
  step: number;
  reward: number;
}

// Mirror of infra/schemas.py LoopStatus.
export type LoopStatus =
  | "running"
  | "completed"
  | "stopped"
  | "budget_exhausted"
  | "failed";

/** Live view of an autonomous session's research loop, folded from round_started /
 *  loop_stopped status events (and seeded from the /full snapshot on resume). */
export interface LoopView {
  /** Current round index (1-based). */
  round: number;
  maxRounds: number;
  goalMetric?: number | null;
  status: LoopStatus;
  /** Why the loop stopped (only set once terminal). */
  reason?: string;
}

export interface JobView {
  id: string;
  parentId: string | null;
  depth: number;
  kind: string;
  status: AgentStatus;
  goal?: string;
  strategy?: string;
  summary?: string;
  lastReward?: number;
  rewards: MetricPoint[];
  artifacts: WireArtifact[];
  /** Insertion order, for stable sibling labels (A/B/C). */
  order: number;
}

export interface TranscriptItem {
  id: string;
  role: "user" | "assistant" | "tool" | "system";
  text: string;
  toolName?: string;
  /** Stable id shared by all token deltas of one streamed message block. */
  msgId?: string;
  /** True while deltas are still arriving (drives the typewriter caret). */
  streaming?: boolean;
}

export interface SessionState {
  sessionId: string | null;
  goal: string;
  rootId: string | null;
  jobs: Record<string, JobView>;
  /** Job ids in first-seen order. */
  order: string[];
  transcript: TranscriptItem[];
  /**
   * Monotonic counter for transcript item ids. Derived deterministically from
   * stream position (incremented per appended item, starting at 0), NOT from a
   * wall clock — so a full replay rebuilds identical ids even after the
   * transcript is capped and earlier items are dropped.
   */
  seq: number;
  /** ISO created_at, from fetchFullSession (#27). */
  startedAt?: string;
  /** Execution backend, e.g. "local" / "cloud_run_job" (from spawn/status). */
  backend?: string;
  /** Session mode, populated from spawn/status payloads when present. */
  mode?: string;
  /** Autonomous loop state, when the session is an autonomous loop. */
  loop?: LoopView;
}

/** SSE connection lifecycle, surfaced to the UI. */
export type ConnPhase =
  | "idle"
  | "connecting"
  | "streaming"
  | "reconnecting"
  | "error"
  | "closed";

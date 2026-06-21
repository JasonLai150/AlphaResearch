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

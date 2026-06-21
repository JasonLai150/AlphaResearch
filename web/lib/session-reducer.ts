import type {
  AgentStatus,
  EventEnvelope,
  JobView,
  SessionState,
  Subagent,
  TranscriptItem,
  TreeNode,
  WireArtifact,
} from "@/lib/types";

/*
  Folds the per-session event stream into live view state. The reducer is the
  single source of truth — replaying the stream from the start fully rebuilds
  state, and metric upserts are idempotent, so reconnects never duplicate.
*/

export function emptyState(
  sessionId: string | null = null,
  goal = ""
): SessionState {
  return {
    sessionId,
    goal,
    rootId: null,
    jobs: {},
    order: [],
    transcript: [],
    seq: 0,
  };
}

// Bound memory on long-running sessions (#29). Caps are generous enough that
// the UI never notices; oldest entries are dropped first.
const MAX_TRANSCRIPT = 2000;
const MAX_REWARDS = 1000;

/*
  Append a transcript item with a collision-free id. The id derives from a
  persistent monotonic `seq` (NOT the array index) so that ids stay unique even
  after the transcript is capped and earlier items are dropped — and so that a
  full deterministic replay rebuilds identical ids. The transcript is capped to
  the most recent MAX_TRANSCRIPT items.
*/
function appendTranscript(
  prev: SessionState,
  item: Omit<TranscriptItem, "id">
): SessionState {
  const seq = prev.seq;
  const next = [...prev.transcript, { ...item, id: `t${seq}` }];
  const transcript =
    next.length > MAX_TRANSCRIPT ? next.slice(next.length - MAX_TRANSCRIPT) : next;
  return { ...prev, transcript, seq: seq + 1 };
}

const STATUS_MAP: Record<string, AgentStatus> = {
  running: "running",
  done: "done",
  failed: "failed",
  queued: "queued",
  pending: "pending",
  cancelled: "cancelled",
};

function mapStatus(s: unknown, fallback: AgentStatus): AgentStatus {
  return (typeof s === "string" && STATUS_MAP[s]) || fallback;
}

export function applyEvent(prev: SessionState, env: EventEnvelope): SessionState {
  const p = env.payload || {};

  // Chat transcript rides the bus as `log` events (role + content).
  if (env.type === "log") {
    const role = String(p.role ?? "assistant");
    // Role mapping: a "tool_use" (agent invoking a tool) and a "tool_result"
    // (the tool's output) both collapse to the single "tool" transcript role;
    // user/system pass through; everything else is the assistant.
    const mapped: TranscriptItem["role"] =
      role === "user"
        ? "user"
        : role === "system"
          ? "system"
          : role === "tool_use" || role === "tool_result"
            ? "tool"
            : "assistant";
    return appendTranscript(prev, {
      role: mapped,
      text: String(p.content ?? ""),
      toolName: (p.tool_name as string) ?? undefined,
    });
  }

  // An `error` event surfaces as a system transcript line (#13).
  if (env.type === "error") {
    return appendTranscript(prev, {
      role: "system",
      text: String(p.reason ?? p.message ?? "agent error"),
    });
  }

  // Backend / mode may arrive on spawn or status payloads (#27); capture them.
  let { backend, mode } = prev;
  if (typeof p.backend === "string") backend = p.backend;
  if (typeof p.mode === "string") mode = p.mode;
  const meta = backend !== prev.backend || mode !== prev.mode ? { backend, mode } : null;

  const id = env.job_id;
  if (!id) {
    // Session-level event (e.g. session_cleaned) — no job; still capture meta.
    return meta ? { ...prev, ...meta } : prev;
  }

  let { rootId, order } = prev;
  let job = prev.jobs[id];
  if (!job) {
    job = {
      id,
      parentId: env.parent_job_id ?? null,
      depth: env.depth ?? 0,
      kind: "agent",
      status: "pending",
      rewards: [],
      artifacts: [],
      order: order.length,
    };
    order = [...order, id];
    if ((env.depth ?? 0) === 0 && !rootId) rootId = id;
  } else {
    job = { ...job, rewards: [...job.rewards], artifacts: [...job.artifacts] };
    if (job.parentId == null && env.parent_job_id) job.parentId = env.parent_job_id;
  }

  switch (env.type) {
    case "status":
      job.status = mapStatus(p.status, job.status);
      break;
    case "spawn":
      if (p.kind) job.kind = String(p.kind);
      if (p.goal) job.goal = String(p.goal);
      if (p.strategy) job.strategy = String(p.strategy);
      if (job.status === "pending") job.status = "queued";
      break;
    case "metric": {
      const step = Number(p.step ?? 0);
      const reward = Number(p.reward);
      if (!Number.isNaN(reward)) {
        const i = job.rewards.findIndex((r) => r.step === step);
        if (i >= 0) job.rewards[i] = { step, reward };
        else job.rewards.push({ step, reward });
        job.rewards.sort((a, b) => a.step - b.step);
        // Cap to the most recent points to bound memory (#29); drop oldest.
        if (job.rewards.length > MAX_REWARDS) {
          job.rewards = job.rewards.slice(job.rewards.length - MAX_REWARDS);
        }
        job.lastReward = reward;
      }
      if (job.status === "pending" || job.status === "queued") job.status = "running";
      break;
    }
    case "summary":
      if (p.summary != null) job.summary = String(p.summary);
      if (p.metrics && typeof p.metrics.final_reward === "number") {
        job.lastReward = p.metrics.final_reward;
      } else if (
        p.metrics &&
        typeof p.metrics.best_reward === "number" &&
        job.lastReward == null
      ) {
        job.lastReward = p.metrics.best_reward;
      }
      // A "partial" reported_status collapses to done (no distinct partial state).
      job.status =
        String(p.reported_status ?? "").toLowerCase() === "failed"
          ? "failed"
          : "done";
      break;
    case "artifact":
      job.artifacts.push({
        id: String(p.artifact_id ?? ""),
        job_id: id,
        kind: String(p.kind ?? "other"),
        url: String(p.url ?? ""),
        caption: (p.caption as string) ?? null,
        bytes: 0,
      });
      break;
  }

  return {
    ...prev,
    ...(meta ?? {}),
    rootId,
    order,
    jobs: { ...prev.jobs, [id]: job },
  };
}

// ─── Selectors ───────────────────────────────────────────────────────────────

function letter(i: number): string {
  return String.fromCharCode(65 + (i % 26)); // A, B, C, ...
}

function childrenOf(state: SessionState, parentId: string): JobView[] {
  return state.order
    .map((id) => state.jobs[id])
    .filter((j) => j.parentId === parentId);
}

export function rootJob(state: SessionState): JobView | null {
  return state.rootId ? state.jobs[state.rootId] ?? null : null;
}

export function subagentsOf(state: SessionState): Subagent[] {
  if (!state.rootId) return [];
  return childrenOf(state, state.rootId).map((j, i) => ({
    id: j.id,
    name: letter(i),
    kind: j.goal || (j.kind === "experiment" ? "Experiment" : "Research"),
    status: j.status,
    reward: j.lastReward,
    rewards: j.rewards,
    note:
      j.lastReward == null
        ? j.status === "queued"
          ? "queued · waiting for a runner"
          : j.summary || j.status
        : undefined,
  }));
}

export function treeOf(state: SessionState): TreeNode | null {
  if (!state.rootId) return null;
  const build = (job: JobView, label: string): TreeNode => ({
    id: job.id,
    label,
    status: job.status,
    children: childrenOf(state, job.id).map((c, i) =>
      build(c, job.depth === 0 ? letter(i) : "")
    ),
  });
  return build(state.jobs[state.rootId], "Main agent");
}

export function artifactsOf(state: SessionState): WireArtifact[] {
  return state.order.flatMap((id) => state.jobs[id].artifacts);
}

/** True while any job is still active (running/queued/pending). */
export function isRunning(state: SessionState): boolean {
  return state.order.some((id) => {
    const s = state.jobs[id].status;
    return s === "running" || s === "queued" || s === "pending";
  });
}

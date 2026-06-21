import type {
  AgentStatus,
  ConsoleLine,
  EventEnvelope,
  GraphLink,
  GraphNode,
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
/** Per-job raw console buffer cap (oldest lines dropped first). */
export const MAX_CONSOLE = 1000;

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

/*
  Stamp a job's live "current line" (for the graph node). Updates ONLY an
  existing job — never creates one — so the invariant "token/log events never
  create jobs" holds. Deterministic under replay (value = latest content). The
  line is tail-trimmed so a long stream can't bloat state.
*/
function stampJobLine(
  state: SessionState,
  id: string,
  line: string,
  streaming: boolean
): SessionState {
  if (!id || !line.trim()) return state;
  const job = state.jobs[id];
  if (!job) return state;
  const trimmed = line.length > 160 ? line.slice(line.length - 160) : line;
  return {
    ...state,
    jobs: { ...state.jobs, [id]: { ...job, lastLine: trimmed, streaming } },
  };
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
    const appended = appendTranscript(prev, {
      role: mapped,
      text: String(p.content ?? ""),
      toolName: (p.tool_name as string) ?? undefined,
    });
    return stampJobLine(appended, env.job_id, String(p.content ?? ""), false);
  }

  // Streaming assistant text: coalesce token deltas into one growing item,
  // keyed by a stable msg_id. Append-only + keyed => idempotent under SSE
  // replay-from-0 and reconnect-resume. Handled here (before job logic) so a
  // token event never creates a phantom job.
  if (env.type === "token") {
    const msgId = String(p.msg_id ?? "");
    const delta = String(p.delta ?? "");
    const final = Boolean(p.final);
    const i = prev.transcript.findIndex((t) => t.msgId === msgId);
    let next: SessionState;
    let line: string;
    if (i >= 0) {
      const transcript = prev.transcript.slice();
      line = transcript[i].text + delta;
      transcript[i] = { ...transcript[i], text: line, streaming: !final };
      next = { ...prev, transcript };
    } else {
      line = delta;
      next = appendTranscript(prev, {
        role: "assistant",
        text: delta,
        msgId,
        streaming: !final,
      });
    }
    return stampJobLine(next, env.job_id, line, !final);
  }

  // Raw console (stdout/stderr) rides the bus as `console` events. It goes into
  // a per-job buffer — NOT the chat transcript — so the operational console has
  // its own view. Like token/log, it only ever updates an EXISTING job (the
  // job's spawn/status precedes its console in the totally-ordered stream), so a
  // console line never creates a phantom job.
  if (env.type === "console") {
    const id = env.job_id;
    const job = id ? prev.jobs[id] : undefined;
    if (!job) return prev;
    const seq = prev.seq;
    const entry: ConsoleLine = {
      id: `c${seq}`,
      stream: p.stream === "stdout" ? "stdout" : "stderr",
      line: String(p.line ?? ""),
    };
    const next = [...(job.console ?? []), entry];
    const buf =
      next.length > MAX_CONSOLE ? next.slice(next.length - MAX_CONSOLE) : next;
    return {
      ...prev,
      seq: seq + 1,
      jobs: { ...prev.jobs, [id]: { ...job, console: buf } },
    };
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
      if (p.summary != null) job.lastLine = String(p.summary);
      job.streaming = false;
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

/** Raw console (stdout/stderr) lines for one job, oldest→newest. */
export function consoleOf(state: SessionState, jobId: string | null): ConsoleLine[] {
  return (jobId && state.jobs[jobId]?.console) || [];
}

/** True while any job is still active (running/queued/pending). */
export function isRunning(state: SessionState): boolean {
  return state.order.some((id) => {
    const s = state.jobs[id].status;
    return s === "running" || s === "queued" || s === "pending";
  });
}

export function graphOf(state: SessionState): {
  nodes: GraphNode[];
  links: GraphLink[];
} {
  if (!state.rootId) return { nodes: [], links: [] };
  let childN = 0;
  const nodes: GraphNode[] = state.order.map((id) => {
    const j = state.jobs[id];
    const isRoot = id === state.rootId;
    let label: string;
    if (isRoot) label = "Main agent";
    else if (j.parentId === state.rootId) label = letter(childN++);
    else label = (j.goal || j.kind).slice(0, 16);
    return {
      id,
      label,
      kind: j.goal || (j.kind === "experiment" ? "Experiment" : "Research"),
      status: j.status,
      depth: j.depth,
      isRoot,
      reward: j.lastReward,
      rewards: j.rewards,
      lastLine: j.lastLine,
      streaming: j.streaming,
    };
  });
  const links: GraphLink[] = state.order
    .map((id) => state.jobs[id])
    .filter((j) => j.parentId != null && state.jobs[j.parentId])
    .map((j) => ({
      source: j.parentId as string,
      target: j.id,
      active: j.status === "running",
    }));
  return { nodes, links };
}

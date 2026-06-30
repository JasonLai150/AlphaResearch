import { StatusDot } from "@/components/status-dot";
import { cn } from "@/lib/utils";
import type { AgentStatus, ConnPhase, LoopView } from "@/lib/types";

/** Human label for a terminal loop status badge. */
const LOOP_STATUS_LABEL: Record<string, string> = {
  running: "running",
  completed: "completed",
  stopped: "stopped",
  budget_exhausted: "budget spent",
  failed: "failed",
};

/** Compact relative-time, e.g. "3m", "2h", "5d". Falls back to "" if unparseable. */
function relTime(iso: string): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  return `${days}d`;
}

/** Thin bar above the transcript: the session goal, root status, live indicator. */
export function SessionHeader({
  goal,
  status,
  phase,
  startedAt,
  onReconnect,
  notFound,
  loop,
  onStop,
  stopping,
}: {
  goal?: string;
  status?: AgentStatus;
  phase: ConnPhase;
  startedAt?: string;
  onReconnect?: () => void;
  notFound?: boolean;
  /** Autonomous loop state, when this is an autonomous session. */
  loop?: LoopView;
  /** Halt the loop (only shown while it is running). */
  onStop?: () => void;
  /** True while the stop request is in flight. */
  stopping?: boolean;
}) {
  if (notFound) {
    return (
      <div className="flex flex-1 items-center justify-center px-6 py-16 text-center">
        <p className="text-[14px] text-mute">
          Session not found — it may have expired.
        </p>
      </div>
    );
  }

  if (!goal) return null;

  const disconnected = phase === "error";

  // Prefer connection trouble, then a terminal run status, then "live" while running.
  let label = "";
  if (phase === "reconnecting" || phase === "connecting") label = "reconnecting";
  else if (disconnected) label = "disconnected";
  else if (status === "done") label = "done";
  else if (status === "failed") label = "failed";
  else if (status === "running") label = "live";

  const accent = label === "live";
  const rel = startedAt ? relTime(startedAt) : "";

  return (
    <div className="flex items-center gap-3 border-b border-hairline px-4 py-3 md:px-6">
      {status && <StatusDot status={status} />}
      <h2 className="min-w-0 flex-1 truncate text-[14px] text-ink">
        {goal}
        {rel && (
          <span className="ml-2 text-[12px] text-mute">· started {rel} ago</span>
        )}
      </h2>
      {loop && (
        <span
          className="shrink-0 font-mono text-[11px] uppercase tracking-wider text-body"
          title={loop.goalMetric != null ? `target metric ${loop.goalMetric}` : undefined}
        >
          Round {loop.round} / {loop.maxRounds}
        </span>
      )}
      {loop && loop.status === "running" && onStop && (
        <button
          type="button"
          onClick={onStop}
          disabled={stopping}
          className={cn(
            "shrink-0 rounded-full border border-hairline bg-canvas-soft px-2.5 py-0.5",
            "font-mono text-[11px] uppercase tracking-wider text-body",
            "transition-colors hover:bg-canvas-card hover:text-ink",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            "disabled:opacity-50"
          )}
        >
          {stopping ? "Stopping…" : "Stop loop"}
        </button>
      )}
      {loop && loop.status !== "running" && (
        <span
          className="shrink-0 font-mono text-[11px] uppercase tracking-wider text-mute"
          title={loop.reason}
        >
          loop {LOOP_STATUS_LABEL[loop.status] ?? loop.status}
        </span>
      )}
      {disconnected && onReconnect && (
        <button
          type="button"
          onClick={onReconnect}
          className={cn(
            "shrink-0 rounded-full border border-hairline bg-canvas-soft px-2.5 py-0.5",
            "font-mono text-[11px] uppercase tracking-wider text-body",
            "transition-colors hover:bg-canvas-card hover:text-ink",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          )}
        >
          Reconnect
        </button>
      )}
      {label && (
        <span
          className={cn(
            "shrink-0 font-mono text-[11px] uppercase tracking-wider",
            accent ? "text-sunset" : "text-mute"
          )}
        >
          {label}
        </span>
      )}
    </div>
  );
}

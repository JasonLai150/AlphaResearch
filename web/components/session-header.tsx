import { StatusDot } from "@/components/status-dot";
import { cn } from "@/lib/utils";
import type { AgentStatus, ConnPhase } from "@/lib/types";

/** Thin bar above the transcript: the session goal, root status, live indicator. */
export function SessionHeader({
  goal,
  status,
  phase,
}: {
  goal?: string;
  status?: AgentStatus;
  phase: ConnPhase;
}) {
  if (!goal) return null;

  // Prefer connection trouble, then a terminal run status, then "live" while running.
  let label = "";
  if (phase === "reconnecting" || phase === "connecting") label = "reconnecting";
  else if (phase === "error") label = "disconnected";
  else if (status === "done") label = "done";
  else if (status === "failed") label = "failed";
  else if (status === "running") label = "live";

  const accent = label === "live";

  return (
    <div className="flex items-center gap-3 border-b border-hairline px-4 py-3 md:px-6">
      {status && <StatusDot status={status} />}
      <h2 className="min-w-0 flex-1 truncate text-[14px] text-ink">{goal}</h2>
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

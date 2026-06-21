import { StatusDot } from "@/components/status-dot";
import { cn } from "@/lib/utils";
import type { AgentStatus, ConnPhase } from "@/lib/types";

const CONN_LABEL: Partial<Record<ConnPhase, string>> = {
  connecting: "connecting",
  streaming: "live",
  reconnecting: "reconnecting",
  error: "disconnected",
};

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
  const conn = CONN_LABEL[phase];
  return (
    <div className="flex items-center gap-3 border-b border-hairline px-4 py-3 md:px-6">
      {status && <StatusDot status={status} />}
      <h2 className="min-w-0 flex-1 truncate text-[14px] text-ink">{goal}</h2>
      {conn && (
        <span
          className={cn(
            "shrink-0 font-mono text-[11px] uppercase tracking-wider",
            phase === "streaming" ? "text-sunset" : "text-mute"
          )}
        >
          {conn}
        </span>
      )}
    </div>
  );
}

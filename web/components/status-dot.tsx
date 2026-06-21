import type { AgentStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const DOT: Record<AgentStatus, string> = {
  running: "bg-sunset",
  done: "bg-ink",
  queued: "bg-mute",
  pending: "bg-mute",
  failed: "bg-destructive",
  cancelled: "bg-mute",
};

const LABEL: Record<AgentStatus, string> = {
  running: "Running",
  done: "Done",
  queued: "Queued",
  pending: "Pending",
  failed: "Failed",
  cancelled: "Cancelled",
};

/** A small status indicator. Decorative dot + a screen-reader status label. */
export function StatusDot({
  status,
  className,
}: {
  status: AgentStatus;
  className?: string;
}) {
  return (
    <span className={cn("relative inline-flex size-1.5", className)}>
      <span
        aria-hidden
        className={cn(
          "inline-flex size-1.5 rounded-full",
          DOT[status],
          status === "running" && "animate-pulse"
        )}
      />
      <span className="sr-only">{LABEL[status]}</span>
    </span>
  );
}

export { LABEL as STATUS_LABEL };

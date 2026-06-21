import Link from "next/link";

import { StatusDot } from "@/components/status-dot";
import { Badge } from "@/components/ui/badge";
import { toAgentStatus } from "@/lib/session-stats";
import { cn, relativeTime } from "@/lib/utils";
import type { WireSession } from "@/lib/types";

/** A single session as a row that links back into the console. */
export function SessionRow({ session }: { session: WireSession }) {
  return (
    <Link
      href={`/?s=${session.id}`}
      className={cn(
        "flex items-center gap-3 rounded-lg border border-hairline bg-canvas-card px-4 py-3 transition-colors hover:bg-canvas-soft",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      )}
    >
      <StatusDot status={toAgentStatus(session.status)} />
      <span className="line-clamp-1 flex-1 text-sm text-ink">
        {session.goal || "Untitled session"}
      </span>
      {session.mode ? (
        <Badge
          variant="secondary"
          className="shrink-0 text-[10px] uppercase tracking-wider"
        >
          {session.mode}
        </Badge>
      ) : null}
      <span className="shrink-0 text-[11px] text-mute">
        {relativeTime(session.created_at)}
      </span>
    </Link>
  );
}

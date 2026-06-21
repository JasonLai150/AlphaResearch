"use client";

import { Clock, Hash, Server, Workflow } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { RepoContext } from "@/lib/types";

/** Relative "started X ago" label from an ISO timestamp. */
function relTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (Number.isNaN(m) || m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

/**
 * The execution-context chip row above the transcript. Chips are built from
 * REAL session fields (#11), mapped onto RepoContext by the page:
 *   env → backend · branch → mode · repo → short session id · worktree → startedAt.
 * Any chip with no real data source is dropped rather than faked.
 */
export function ContextBar({ ctx }: { ctx: RepoContext }) {
  const chips = [
    { key: "env", icon: Server, label: ctx.env, tip: "Execution backend" },
    { key: "mode", icon: Workflow, label: ctx.branch, tip: "Run mode" },
    { key: "id", icon: Hash, label: ctx.repo, tip: "Session id", muted: true },
    {
      key: "started",
      icon: Clock,
      label: ctx.worktree ? relTime(ctx.worktree) : "",
      tip: "Session started",
      muted: true,
    },
  ].filter((c) => c.label);

  if (!chips.length) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-hairline px-4 py-3 md:px-6">
      {chips.map(({ key, icon: Icon, label, tip, muted }) => (
        <Tooltip key={key}>
          <TooltipTrigger asChild>
            <span
              className={cn(
                "inline-flex cursor-default items-center gap-1.5 rounded-full border border-hairline px-3 py-1 text-xs transition-colors hover:bg-canvas-soft",
                muted ? "text-mute" : "text-body"
              )}
            >
              <Icon className="size-3.5" aria-hidden />
              {label}
            </span>
          </TooltipTrigger>
          <TooltipContent>{tip}</TooltipContent>
        </Tooltip>
      ))}
    </div>
  );
}

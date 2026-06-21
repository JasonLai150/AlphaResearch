"use client";

import { FolderGit2, GitBranch, GitFork, Server } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { RepoContext } from "@/lib/types";

/** The execution-context chip row above the transcript. */
export function ContextBar({ ctx }: { ctx: RepoContext }) {
  const chips = [
    { icon: Server, label: ctx.env, tip: "Execution target" },
    { icon: FolderGit2, label: ctx.repo, tip: "Repository" },
    { icon: GitBranch, label: ctx.branch, tip: "Active branch" },
    {
      icon: GitFork,
      label: ctx.worktree,
      tip: "Isolated git worktree",
      muted: true,
    },
  ];

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-hairline px-4 py-3 md:px-6">
      {chips.map(({ icon: Icon, label, tip, muted }) => (
        <Tooltip key={label}>
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

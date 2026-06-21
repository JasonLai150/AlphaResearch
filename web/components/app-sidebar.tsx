"use client";

import { useState } from "react";
import {
  ChevronsUpDown,
  FolderClosed,
  LayoutGrid,
  Plug,
  Plus,
  Search,
  Settings,
  Sparkles,
} from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Eyebrow } from "@/components/eyebrow";
import { cn } from "@/lib/utils";
import type { CurrentUser, WireSession } from "@/lib/types";

const NAV = [
  { key: "overview", label: "Overview", icon: LayoutGrid },
  { key: "integrations", label: "Integrations", icon: Plug },
  { key: "projects", label: "Projects", icon: FolderClosed },
] as const;

const focusRing =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function relTime(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const m = Math.floor(ms / 60000);
  if (Number.isNaN(m) || m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

export function AppSidebar({
  sessions,
  activeId,
  onSelect,
  onNew,
  user,
}: {
  sessions: WireSession[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  user: CurrentUser;
}) {
  const [activeNav, setActiveNav] = useState<string>("overview");
  const [filter, setFilter] = useState("");

  const shown = sessions.filter((s) =>
    (s.goal || "").toLowerCase().includes(filter.trim().toLowerCase())
  );

  return (
    <aside className="flex h-full min-h-0 w-full flex-col gap-5 border-r border-hairline bg-canvas px-3 py-4">
      <div className="flex items-center gap-2 px-2">
        <Sparkles className="size-4 text-sunset" aria-hidden />
        <span className="text-[15px] tracking-[-0.01em]">Alpha Research</span>
      </div>

      <nav className="flex flex-col gap-0.5">
        {NAV.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setActiveNav(key)}
            aria-current={activeNav === key ? "page" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
              focusRing,
              activeNav === key
                ? "bg-canvas-soft text-ink"
                : "text-body hover:bg-canvas-soft hover:text-ink"
            )}
          >
            <Icon className="size-4" aria-hidden />
            {label}
          </button>
        ))}
      </nav>

      <div className="flex min-h-0 flex-1 flex-col gap-2.5">
        <div className="flex items-center justify-between px-2">
          <Eyebrow as="h2">Chats</Eyebrow>
          <Button
            variant="ghost"
            size="icon"
            className="size-6"
            aria-label="New chat"
            onClick={onNew}
          >
            <Plus className="size-4" />
          </Button>
        </div>

        <div className="relative px-1">
          <Search
            className="pointer-events-none absolute left-3.5 top-1/2 size-3.5 -translate-y-1/2 text-mute"
            aria-hidden
          />
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter chats"
            aria-label="Filter chats"
            className="h-9 pl-9 text-[13px]"
          />
        </div>

        <ScrollArea className="-mx-1 min-h-0 flex-1">
          <div className="flex flex-col gap-0.5 px-1">
            {shown.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => onSelect(s.id)}
                aria-current={activeId === s.id ? "true" : undefined}
                className={cn(
                  "flex items-center gap-2 rounded-full border px-3.5 py-2 text-left transition-colors",
                  focusRing,
                  activeId === s.id
                    ? "border-hairline bg-canvas-card text-ink"
                    : "border-transparent text-body hover:bg-canvas-soft"
                )}
              >
                <span className="line-clamp-1 flex-1 text-[13px]">
                  {s.goal || "Untitled session"}
                </span>
                <span className="shrink-0 text-[11px] text-mute">
                  {relTime(s.created_at)}
                </span>
              </button>
            ))}
            {!shown.length && (
              <p className="px-3 py-6 text-center text-[12px] text-mute">
                {sessions.length
                  ? `No chats match “${filter}”.`
                  : "No sessions yet — start one below."}
              </p>
            )}
          </div>
        </ScrollArea>
      </div>

      <div className="flex flex-col gap-1 border-t border-hairline pt-3">
        <button
          type="button"
          className={cn(
            "flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-body transition-colors hover:bg-canvas-soft hover:text-ink",
            focusRing
          )}
        >
          <Settings className="size-4" aria-hidden />
          Settings
        </button>
        <button
          type="button"
          className={cn(
            "flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-canvas-soft",
            focusRing
          )}
        >
          <Avatar className="size-7">
            <AvatarFallback className="text-[11px]">
              {user.initials}
            </AvatarFallback>
          </Avatar>
          <div className="flex min-w-0 flex-col items-start gap-0.5 leading-tight">
            <span className="line-clamp-1 max-w-[120px] text-[13px]">
              {user.handle}
            </span>
            <Badge
              variant="secondary"
              className="px-1.5 py-0 text-[10px] uppercase tracking-wider"
            >
              {user.role}
            </Badge>
          </div>
          <ChevronsUpDown className="ml-auto size-4 text-mute" aria-hidden />
        </button>
      </div>
    </aside>
  );
}

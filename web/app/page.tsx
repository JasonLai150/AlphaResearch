"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Menu, Network, Sparkles } from "lucide-react";

import { useAppAuth } from "@/components/auth/app-auth";
import { AppSidebar } from "@/components/app-sidebar";
import { ChatComposer } from "@/components/chat-composer";
import { ChatTranscript } from "@/components/chat-transcript";
import { ContextBar } from "@/components/context-bar";
import { Eyebrow } from "@/components/eyebrow";
import { ResizeHandle } from "@/components/resize-handle";
import { SessionHeader } from "@/components/session-header";
import { TreePanel } from "@/components/tree-panel";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useChatSubmit } from "@/hooks/use-chat-submit";
import { useResizablePane } from "@/hooks/use-resizable-pane";
import { useSession } from "@/hooks/use-session";
import { useSessions } from "@/hooks/use-sessions";
import {
  artifactsOf,
  rootJob,
  subagentsOf,
  treeOf,
} from "@/lib/session-reducer";
import type { RepoContext, TranscriptItem } from "@/lib/types";

export default function Page() {
  const { userId, getToken } = useAppAuth();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [treeOpen, setTreeOpen] = useState(false);

  const {
    width: sidebarWidth,
    nudge: nudgeSidebar,
    reset: resetSidebar,
  } = useResizablePane({ key: "ar.sidebarWidth", min: 200, max: 480, initial: 264 });

  const { sessions, loading, refresh } = useSessions(userId, getToken);
  const { state, phase, notFound, reconnect } = useSession(activeId, getToken);

  function select(id: string | null) {
    setActiveId(id);
    setSidebarOpen(false);
    setTreeOpen(false);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("s", id);
    else url.searchParams.delete("s");
    window.history.replaceState({}, "", url.toString());
  }

  const { busy, pending, optimistic, onSubmit, settle, reconcile } =
    useChatSubmit({
      activeId,
      userId,
      getToken,
      onCreate: (sessionId) => {
        select(sessionId);
        // The sessions hook polls every 8s; one immediate refresh surfaces the
        // new chat in the sidebar without waiting for the next tick.
        refresh();
      },
    });

  // Restore the active session from the URL (?s=) on first load.
  useEffect(() => {
    const s = new URLSearchParams(window.location.search).get("s");
    if (s) setActiveId(s);
  }, []);

  // Stop the "working" indicator once the assistant replies (#3).
  const lastRole = state.transcript[state.transcript.length - 1]?.role;
  useEffect(() => {
    if (lastRole === "assistant") settle();
  }, [lastRole, state.transcript.length, settle]);

  // Reconcile the optimistic echo (#8): once the server transcript carries a
  // matching user message, drop the local echo so it never double-renders.
  const serverEchoed = useMemo(() => {
    if (!optimistic) return false;
    return state.transcript.some(
      (t) => t.role === "user" && t.text === optimistic.text
    );
  }, [optimistic, state.transcript]);
  useEffect(() => {
    reconcile(serverEchoed);
  }, [serverEchoed, reconcile]);

  // Merge the optimistic user echo into the rendered transcript until the
  // server confirms it (#8). Never append when the server already has it.
  const items: TranscriptItem[] = useMemo(() => {
    if (optimistic && !serverEchoed) return [...state.transcript, optimistic];
    return state.transcript;
  }, [optimistic, serverEchoed, state.transcript]);

  const root = rootJob(state);
  // Working while the lead agent is active, or a follow-up is awaiting a reply.
  // (A parked, queued sub-agent shouldn't keep the indicator spinning forever.)
  const running =
    (root
      ? root.status === "running" || root.status === "pending"
      : phase === "connecting" || phase === "streaming") || pending;

  // Build the execution-context chips from REAL session fields (#11): backend
  // env, mode, a short session id, and the relative started-time. Chips with no
  // real source are dropped by ContextBar (empty label).
  const ctx: RepoContext = {
    env: state.backend ?? "",
    repo: activeId ? activeId.slice(0, 8) : "",
    branch: state.mode ?? "",
    worktree: state.startedAt ?? "",
  };

  const tree = treeOf(state);
  const subagents = subagentsOf(state);
  const artifacts = artifactsOf(state);

  const sidebar = (
    <AppSidebar
      sessions={sessions}
      activeId={activeId}
      onSelect={(id) => select(id)}
      onNew={() => select(null)}
      loading={loading}
    />
  );

  const rightRail = (
    <TreePanel tree={tree} subagents={subagents} artifacts={artifacts} />
  );

  return (
    <TooltipProvider delayDuration={150}>
      <div className="flex h-screen w-full overflow-hidden bg-canvas text-ink">
        {/* Desktop sidebar (≥ md). Below md it becomes a slide-over drawer. */}
        <div
          className="hidden shrink-0 md:flex"
          style={{ width: sidebarWidth }}
        >
          {sidebar}
        </div>
        <ResizeHandle
          className="hidden md:block"
          onResize={nudgeSidebar}
          onReset={resetSidebar}
        />
        <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
          <SheetContent side="left" className="w-[300px] p-0">
            {sidebar}
          </SheetContent>
        </Sheet>

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          {/* Mobile / tablet top bar with drawer triggers. */}
          <header className="flex items-center gap-2 border-b border-hairline px-3 py-3 xl:hidden">
            <Button
              variant="ghost"
              size="icon"
              className="size-8 md:hidden"
              aria-label="Open chats"
              onClick={() =>
                activeId ? select(null) : setSidebarOpen(true)
              }
            >
              {activeId ? (
                <ArrowLeft className="size-4" />
              ) : (
                <Menu className="size-4" />
              )}
            </Button>
            <Sparkles className="size-4 text-sunset md:hidden" aria-hidden />
            <span className="flex-1 truncate text-sm">Alpha Research</span>
            {activeId && (
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                aria-label="Open agent tree"
                onClick={() => setTreeOpen(true)}
              >
                <Network className="size-4" />
              </Button>
            )}
          </header>

          {activeId ? (
            <>
              <SessionHeader
                goal={state.goal}
                status={root?.status}
                phase={phase}
                startedAt={state.startedAt}
                onReconnect={reconnect}
                notFound={notFound}
              />
              {!notFound && (
                <>
                  <ContextBar ctx={ctx} />
                  <ChatTranscript items={items} running={running} />
                  <ChatComposer
                    onSubmit={onSubmit}
                    busy={busy}
                    placeholder="Reply to the lead agent…"
                  />
                </>
              )}
            </>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-6 px-6">
              <div className="flex flex-col items-center gap-3 text-center">
                <Sparkles className="size-7 text-sunset" aria-hidden />
                <Eyebrow>New research session</Eyebrow>
                <h1 className="max-w-xl text-2xl tracking-[-0.02em] text-ink">
                  What should the lead agent investigate?
                </h1>
                <p className="max-w-md text-sm text-mute">
                  Describe a research goal. The lead agent scopes it, fans out
                  independent sub-agents, and streams results back here live.
                </p>
              </div>
              <div className="w-full max-w-2xl">
                <ChatComposer
                  onSubmit={onSubmit}
                  busy={busy}
                  placeholder="e.g. Improve PPO sample efficiency on MiniGrid-DoorKey-8x8…"
                  hint="Press Enter to start the run"
                />
              </div>
            </div>
          )}
        </main>

        {/* Desktop right rail (≥ xl). Below xl it becomes a slide-over drawer. */}
        <div className="hidden w-[320px] shrink-0 xl:flex">{rightRail}</div>
        <Sheet open={treeOpen} onOpenChange={setTreeOpen}>
          <SheetContent side="right" className="w-[340px] p-0">
            {rightRail}
          </SheetContent>
        </Sheet>
      </div>
    </TooltipProvider>
  );
}

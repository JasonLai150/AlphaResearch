"use client";

import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";

import { useAppAuth } from "@/components/auth/app-auth";
import { AppSidebar } from "@/components/app-sidebar";
import { ChatComposer } from "@/components/chat-composer";
import { ChatTranscript } from "@/components/chat-transcript";
import { ContextBar } from "@/components/context-bar";
import { Eyebrow } from "@/components/eyebrow";
import { SessionHeader } from "@/components/session-header";
import { TreePanel } from "@/components/tree-panel";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useSession } from "@/hooks/use-session";
import { useSessions } from "@/hooks/use-sessions";
import { createSession, sendMessage } from "@/lib/api";
import {
  artifactsOf,
  rootJob,
  subagentsOf,
  treeOf,
} from "@/lib/session-reducer";
import { repoContext } from "@/lib/mock-data";

export default function Page() {
  const { userId, getToken } = useAppAuth();
  const [activeId, setActiveId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { sessions, refresh } = useSessions(userId, getToken);
  const { state, phase } = useSession(activeId, getToken);

  // Restore the active session from the URL (?s=) on first load.
  useEffect(() => {
    const s = new URLSearchParams(window.location.search).get("s");
    if (s) setActiveId(s);
  }, []);

  function select(id: string | null) {
    setActiveId(id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("s", id);
    else url.searchParams.delete("s");
    window.history.replaceState({}, "", url.toString());
  }

  async function onSubmit(text: string) {
    setBusy(true);
    try {
      if (!activeId) {
        const token = await getToken();
        const { session_id } = await createSession({ userId, goal: text }, token);
        select(session_id);
        // Give the session a moment to register, then refresh the sidebar.
        setTimeout(refresh, 400);
      } else {
        await sendMessage(activeId, text, await getToken());
      }
    } catch (e) {
      console.error("submit failed", e);
    } finally {
      setBusy(false);
    }
  }

  const root = rootJob(state);
  // The run is "working" while the lead agent is active (a parked, queued
  // sub-agent shouldn't keep the indicator spinning forever).
  const running = root
    ? root.status === "running" || root.status === "pending"
    : phase === "connecting" || phase === "streaming";

  return (
    <TooltipProvider delayDuration={150}>
      <div className="flex h-screen w-full overflow-hidden bg-canvas text-ink">
        <div className="hidden w-[264px] shrink-0 md:flex">
          <AppSidebar
            sessions={sessions}
            activeId={activeId}
            onSelect={select}
            onNew={() => select(null)}
          />
        </div>

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          <header className="flex items-center gap-2 border-b border-hairline px-4 py-3 md:hidden">
            <Sparkles className="size-4 text-sunset" aria-hidden />
            <span className="text-sm">Alpha Research</span>
          </header>

          {activeId ? (
            <>
              <SessionHeader goal={state.goal} status={root?.status} phase={phase} />
              <ContextBar ctx={repoContext} />
              <ChatTranscript items={state.transcript} running={running} />
              <ChatComposer
                onSubmit={onSubmit}
                busy={busy}
                placeholder="Reply to the lead agent…"
              />
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

        <div className="hidden w-[320px] shrink-0 xl:flex">
          <TreePanel
            tree={treeOf(state)}
            subagents={subagentsOf(state)}
            artifacts={artifactsOf(state)}
          />
        </div>
      </div>
    </TooltipProvider>
  );
}

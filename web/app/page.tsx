import { Sparkles } from "lucide-react";

import { AppSidebar } from "@/components/app-sidebar";
import { ChatComposer } from "@/components/chat-composer";
import { ChatTranscript } from "@/components/chat-transcript";
import { ContextBar } from "@/components/context-bar";
import { TreePanel } from "@/components/tree-panel";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  agentTree,
  chats,
  currentUser,
  messages,
  repoContext,
  subagents,
} from "@/lib/mock-data";

/*
  Overview dashboard — the 3-pane research console from the sketch:
  left sidebar (nav + chat history), center transcript with the repo context
  bar and composer, right "Tree" rail with the agent graph + subagents.
*/
export default function Page() {
  return (
    <TooltipProvider delayDuration={150}>
      <div className="flex h-screen w-full overflow-hidden bg-canvas text-ink">
        <div className="hidden w-[264px] shrink-0 md:flex">
          <AppSidebar chats={chats} user={currentUser} />
        </div>

        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          <h1 className="sr-only">Alpha Research — Overview</h1>
          <header className="flex items-center gap-2 border-b border-hairline px-4 py-3 md:hidden">
            <Sparkles className="size-4 text-sunset" aria-hidden />
            <span className="text-sm">Alpha Research</span>
          </header>

          <ContextBar ctx={repoContext} />
          <ChatTranscript messages={messages} />
          <ChatComposer />
        </main>

        <div className="hidden w-[320px] shrink-0 xl:flex">
          <TreePanel tree={agentTree} subagents={subagents} />
        </div>
      </div>
    </TooltipProvider>
  );
}

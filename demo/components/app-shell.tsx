"use client";

import {
  createContext,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { Menu, Sparkles } from "lucide-react";

import { useAppAuth } from "@/components/auth/app-auth";
import { AppSidebar } from "@/components/app-sidebar";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useSessions } from "@/hooks/use-sessions";
import type { WireSession } from "@/lib/types";

interface ShellSessions {
  sessions: WireSession[];
  loading: boolean;
  refresh: () => void;
}

// AppShell owns the one session poller for the secondary pages (the sidebar
// needs it anyway); pages read the same data via this context instead of
// spinning up a second poller. Single source of truth for the session list.
const SessionsCtx = createContext<ShellSessions>({
  sessions: [],
  loading: false,
  refresh: () => {},
});

export const useShellSessions = () => useContext(SessionsCtx);

/**
 * The persistent shell for the secondary pages (overview, integrations,
 * projects, settings, account). Renders the same AppSidebar as the console so
 * navigation is identical, plus a scrollable content area for the page. The
 * console at app/page.tsx keeps its own bespoke 3-pane layout and does NOT use
 * this shell. Selecting a chat or starting a new one routes back to the console.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { userId, getToken } = useAppAuth();
  const { sessions, loading, refresh } = useSessions(userId, getToken);
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const sidebar = (
    <AppSidebar
      sessions={sessions}
      activeId={null}
      onSelect={(id) => {
        setSidebarOpen(false);
        router.push(`/?s=${id}`);
      }}
      onNew={() => {
        setSidebarOpen(false);
        router.push("/");
      }}
      loading={loading}
    />
  );

  return (
    <TooltipProvider delayDuration={150}>
      <SessionsCtx.Provider value={{ sessions, loading, refresh }}>
        <div className="flex h-screen w-full overflow-hidden bg-canvas text-ink">
          {/* Desktop sidebar (≥ md); below md it becomes a slide-over drawer. */}
          <div className="hidden w-[264px] shrink-0 md:flex">{sidebar}</div>
          <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
            <SheetContent side="left" className="w-[300px] p-0">
              {sidebar}
            </SheetContent>
          </Sheet>

          <main className="flex min-h-0 min-w-0 flex-1 flex-col">
            {/* Mobile top bar with the drawer trigger. */}
            <header className="flex items-center gap-2 border-b border-hairline px-3 py-3 md:hidden">
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                aria-label="Open navigation"
                onClick={() => setSidebarOpen(true)}
              >
                <Menu className="size-4" />
              </Button>
              <Sparkles className="size-4 text-sunset" aria-hidden />
              <span className="flex-1 truncate text-sm">Alpha Research</span>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
          </main>
        </div>
      </SessionsCtx.Provider>
    </TooltipProvider>
  );
}

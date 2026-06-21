import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import type { CurrentUser } from "@/lib/types";

// ── Mocks ────────────────────────────────────────────────────────────────────
// AppSidebar pulls in Clerk's <UserButton> and the useAppAuth hook. Neither has
// a provider in the test tree, so stub both: a trivial UserButton and a stable
// keyless ("clerk: false") auth value mirroring the demo path.
vi.mock("@clerk/nextjs", () => ({
  UserButton: () => <div data-testid="user-button" />,
}));

const DEMO_USER: CurrentUser = {
  name: "Demo User",
  handle: "demo",
  role: "Member",
  initials: "D",
};

vi.mock("@/components/auth/app-auth", () => ({
  useAppAuth: () => ({
    userId: "demo",
    user: DEMO_USER,
    getToken: async () => undefined,
    clerk: false,
  }),
}));

import { AppSidebar } from "@/components/app-sidebar";
import { ChatTranscript } from "@/components/chat-transcript";
import { SessionHeader } from "@/components/session-header";
import { TreePanel } from "@/components/tree-panel";

// jsdom lacks ResizeObserver (Radix ScrollArea) and scrollIntoView
// (ChatTranscript auto-scroll). Polyfill them so the components mount.
beforeAll(() => {
  if (!("ResizeObserver" in globalThis)) {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  }
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = () => {};
  }
});

// With `globals: false`, RTL does not auto-register cleanup — do it ourselves so
// renders don't leak into the next test in this file.
afterEach(() => {
  cleanup();
});

describe("ChatTranscript states", () => {
  it("shows the empty state with no items and not running", () => {
    render(<ChatTranscript items={[]} running={false} />);

    expect(screen.getByText("No messages yet.")).toBeInTheDocument();
    expect(
      screen.queryByRole("status", { name: "Lead agent is working" })
    ).not.toBeInTheDocument();
  });

  it("shows the working indicator while running", () => {
    render(<ChatTranscript items={[]} running />);

    expect(
      screen.getByRole("status", { name: "Lead agent is working" })
    ).toBeInTheDocument();
    expect(screen.getByText("Working…")).toBeInTheDocument();
    // The empty state is suppressed while the agent is working.
    expect(screen.queryByText("No messages yet.")).not.toBeInTheDocument();
  });
});

describe("AppSidebar states", () => {
  const noop = () => {};

  it("shows the empty text when there are no sessions", () => {
    render(
      <AppSidebar
        sessions={[]}
        activeId={null}
        onSelect={noop}
        onNew={noop}
      />
    );

    expect(screen.getByText(/No sessions yet/i)).toBeInTheDocument();
  });

  it("shows skeleton rows while loading with no sessions", () => {
    const { container } = render(
      <AppSidebar
        sessions={[]}
        activeId={null}
        onSelect={noop}
        onNew={noop}
        loading
      />
    );

    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(
      0
    );
    // While skeletons are showing the empty copy must not appear.
    expect(screen.queryByText(/No sessions yet/i)).not.toBeInTheDocument();
  });
});

describe("SessionHeader states", () => {
  it("shows the not-found message", () => {
    render(<SessionHeader phase="idle" notFound />);

    expect(
      screen.getByText(/Session not found/i)
    ).toBeInTheDocument();
  });

  it("shows 'disconnected' and a Reconnect control on error", () => {
    const onReconnect = vi.fn();
    render(
      <SessionHeader
        goal="Tune the reward model"
        status="running"
        phase="error"
        onReconnect={onReconnect}
      />
    );

    expect(screen.getByText("disconnected")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Reconnect" })
    ).toBeInTheDocument();
  });
});

describe("TreePanel states", () => {
  it("shows the empty agent-tree and subagents copy", () => {
    render(<TreePanel tree={null} subagents={[]} artifacts={[]} />);

    expect(screen.getByText("No agents yet.")).toBeInTheDocument();
    expect(screen.getByText("None dispatched yet.")).toBeInTheDocument();
  });

  it("fires onExpand when the tree is clicked", () => {
    const onExpand = vi.fn();
    const tree = { id: "root", label: "Main agent", status: "running" as const, children: [] };
    render(<TreePanel tree={tree} subagents={[]} artifacts={[]} onExpand={onExpand} />);
    fireEvent.click(screen.getByRole("button", { name: /expand agent graph/i }));
    expect(onExpand).toHaveBeenCalledTimes(1);
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import type { CurrentUser, WireSession } from "@/lib/types";
import { getDefaultBudget } from "@/lib/settings-store";

// Shared mutable state the mocks read, so each test can set up its own world.
const h = vi.hoisted(() => ({
  sessions: [] as WireSession[],
  loading: false,
}));

vi.mock("@/components/app-shell", () => ({
  useShellSessions: () => ({
    sessions: h.sessions,
    loading: h.loading,
    refresh: () => {},
  }),
}));

vi.mock("@/hooks/use-health", () => ({
  useHealth: () => ({ status: "ok", recheck: () => {} }),
}));

vi.mock("sonner", () => ({ toast: { success: () => {}, error: () => {} } }));

const DEMO_USER: CurrentUser = {
  name: "Demo User",
  handle: "demo",
  role: "Dev",
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
vi.mock("@clerk/nextjs", () => ({
  UserProfile: () => <div data-testid="clerk-user-profile" />,
}));

import OverviewPage from "@/app/(shell)/overview/page";
import IntegrationsPage from "@/app/(shell)/integrations/page";
import SettingsPage from "@/app/(shell)/settings/page";
import AccountPage from "@/app/(shell)/account/page";

function mk(p: Partial<WireSession>): WireSession {
  return {
    id: p.id ?? "s",
    user_id: "u",
    goal: p.goal ?? "goal",
    mode: p.mode ?? "default",
    status: p.status ?? "pending",
    created_at: p.created_at ?? "2026-06-21T08:00:00Z",
    root_job_id: null,
  };
}

/** The value span of a stat card identified by its label (scoped to the stats
 * region, so it never collides with StatusDot's sr-only status labels). */
function statValue(label: string): string | null {
  const region = screen.getByRole("region", { name: "Session statistics" });
  const card = within(region).getByText(label).parentElement!;
  return card.querySelector("span")!.textContent;
}

describe("Overview page", () => {
  it("counts sessions into the stat cards", () => {
    h.loading = false;
    h.sessions = [
      mk({ id: "a", status: "running" }),
      mk({ id: "b", status: "running" }),
      mk({ id: "c", status: "done" }),
    ];
    render(<OverviewPage />);
    expect(statValue("Total sessions")).toBe("3");
    expect(statValue("Running")).toBe("2");
    expect(statValue("Completed")).toBe("1");
    expect(statValue("Failed")).toBe("0");
  });

  it("shows the empty state with no sessions", () => {
    h.loading = false;
    h.sessions = [];
    render(<OverviewPage />);
    expect(screen.getByText(/No research sessions yet/i)).toBeInTheDocument();
  });
});

describe("Integrations page", () => {
  it("shows the live backend status and the managed-service cards", () => {
    render(<IntegrationsPage />);
    // Health mock returns "ok" → Connected.
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Modal")).toBeInTheDocument();
    expect(screen.getByText("Redis")).toBeInTheDocument();
    // Honest labeling for services the frontend can't verify.
    expect(screen.getAllByText("Managed on backend").length).toBeGreaterThan(0);
  });
});

describe("Settings page", () => {
  beforeEach(() => localStorage.clear());

  it("persists a saved default budget", () => {
    render(<SettingsPage />);
    const input = screen.getByLabelText(/Default budget/i);
    fireEvent.change(input, { target: { value: "25" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(getDefaultBudget()).toBe(25);
  });
});

describe("Account page", () => {
  it("renders the keyless profile card (not the Clerk profile)", () => {
    render(<AccountPage />);
    expect(screen.getByText("Demo User")).toBeInTheDocument();
    expect(screen.getByText(/keyless dev mode/i)).toBeInTheDocument();
    expect(screen.queryByTestId("clerk-user-profile")).not.toBeInTheDocument();
  });
});

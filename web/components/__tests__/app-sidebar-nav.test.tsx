import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import type { CurrentUser } from "@/lib/types";

// AppSidebar pulls in Clerk's <UserButton> and useAppAuth; stub both (keyless).
vi.mock("@clerk/nextjs", () => ({
  UserButton: () => <div data-testid="user-button" />,
}));

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

// Drive a specific path so the active-state logic has something to match.
vi.mock("next/navigation", () => ({
  usePathname: () => "/integrations",
  useRouter: () => ({
    push: () => {},
    replace: () => {},
    back: () => {},
    forward: () => {},
    refresh: () => {},
    prefetch: () => {},
  }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AppSidebar } from "@/components/app-sidebar";

const noop = () => {};

function renderSidebar() {
  return render(
    <AppSidebar sessions={[]} activeId={null} onSelect={noop} onNew={noop} />
  );
}

describe("AppSidebar navigation", () => {
  it("marks the link matching the current path as active", () => {
    renderSidebar();
    expect(
      screen.getByRole("link", { name: /Integrations/i })
    ).toHaveAttribute("aria-current", "page");
    expect(
      screen.getByRole("link", { name: /Overview/i })
    ).not.toHaveAttribute("aria-current");
  });

  it("points nav items, Settings, and the profile at real routes", () => {
    renderSidebar();
    expect(screen.getByRole("link", { name: /Overview/i })).toHaveAttribute(
      "href",
      "/overview"
    );
    expect(screen.getByRole("link", { name: /Settings/i })).toHaveAttribute(
      "href",
      "/settings"
    );
    // The keyless profile row links to the account page.
    expect(screen.getByRole("link", { name: /demo/i })).toHaveAttribute(
      "href",
      "/account"
    );
  });
});

import { beforeAll, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { LandingHero } from "@/components/landing/landing-hero";

beforeAll(() => {
  // jsdom has no canvas — force the graph field's early-return path so the hero
  // renders cleanly (and to silence the "not implemented" virtual-console noise).
  HTMLCanvasElement.prototype.getContext = (() => null) as never;
});

describe("LandingHero", () => {
  it("renders the pitch as the H1", () => {
    render(<LandingHero />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Recursive sandboxed agents for autonomous RL research at scale"
    );
  });

  it("renders the primary CTA as a launch button, not a direct link", () => {
    render(<LandingHero />);
    // A demo password gate now sits in front of the console, so the CTA opens
    // a modal rather than linking straight to /app.
    expect(
      screen.getByRole("button", { name: "Launch app" })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Launch app" })
    ).not.toBeInTheDocument();
  });

  it("offers a sign-in link in the nav", () => {
    render(<LandingHero />);
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/sign-in"
    );
  });
});

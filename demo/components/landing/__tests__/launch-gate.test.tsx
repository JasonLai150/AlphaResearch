import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { DEMO_PASSWORD, LaunchGate } from "@/components/landing/launch-gate";

// The gate navigates with a full-page assign (no Next router context needed in
// jsdom). Swap window.location for a spy so we can assert navigation without
// jsdom's "not implemented: navigation" noise.
const originalLocation = window.location;
let assign: ReturnType<typeof vi.fn>;

beforeEach(() => {
  assign = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...originalLocation, assign },
  });
});

afterEach(() => {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: originalLocation,
  });
});

describe("LaunchGate", () => {
  it("renders the CTA but no modal until clicked", () => {
    render(<LaunchGate />);

    expect(
      screen.getByRole("button", { name: "Launch app" })
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("opens the password modal when the CTA is clicked", () => {
    render(<LaunchGate />);

    fireEvent.click(screen.getByRole("button", { name: "Launch app" }));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Demo password")).toBeInTheDocument();
  });

  it("rejects a wrong password with an error and does not navigate", () => {
    render(<LaunchGate />);
    fireEvent.click(screen.getByRole("button", { name: "Launch app" }));

    fireEvent.change(screen.getByLabelText("Demo password"), {
      target: { value: "0000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /enter/i }));

    expect(screen.getByText(/incorrect password/i)).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });

  it("clears the error once the user edits the password again", () => {
    render(<LaunchGate />);
    fireEvent.click(screen.getByRole("button", { name: "Launch app" }));

    const input = screen.getByLabelText("Demo password");
    fireEvent.change(input, { target: { value: "0000" } });
    fireEvent.click(screen.getByRole("button", { name: /enter/i }));
    expect(screen.getByText(/incorrect password/i)).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "1" } });
    expect(screen.queryByText(/incorrect password/i)).not.toBeInTheDocument();
  });

  it("navigates to /app when the demo password is correct", () => {
    render(<LaunchGate />);
    fireEvent.click(screen.getByRole("button", { name: "Launch app" }));

    fireEvent.change(screen.getByLabelText("Demo password"), {
      target: { value: DEMO_PASSWORD },
    });
    fireEvent.click(screen.getByRole("button", { name: /enter/i }));

    expect(assign).toHaveBeenCalledWith("/app");
  });
});

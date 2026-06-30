import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConsolePanel } from "@/components/console-panel";
import type { ConsoleLine } from "@/lib/types";

function line(over: Partial<ConsoleLine>): ConsoleLine {
  return { id: "c0", stream: "stdout", line: "hello", ...over };
}

describe("ConsolePanel", () => {
  it("renders each console line in order", () => {
    render(
      <ConsolePanel
        lines={[line({ id: "c0", line: "boot" }), line({ id: "c1", line: "step 1" })]}
      />
    );
    expect(screen.getByText("boot")).toBeInTheDocument();
    expect(screen.getByText("step 1")).toBeInTheDocument();
  });

  it("tags stderr lines so they can be styled distinctly", () => {
    render(<ConsolePanel lines={[line({ id: "c0", stream: "stderr", line: "warn" })]} />);
    const row = screen.getByText("warn").closest("[data-stream]");
    expect(row?.getAttribute("data-stream")).toBe("stderr");
  });

  it("shows an empty state when there is no console output", () => {
    render(<ConsolePanel lines={[]} />);
    expect(screen.getByText(/no console output/i)).toBeInTheDocument();
  });
});

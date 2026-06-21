import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { clampWidth, useResizablePane } from "@/hooks/use-resizable-pane";

describe("clampWidth", () => {
  it("clamps below min and above max, passes through in range", () => {
    expect(clampWidth(120, 200, 480)).toBe(200);
    expect(clampWidth(900, 200, 480)).toBe(480);
    expect(clampWidth(300, 200, 480)).toBe(300);
  });
});

describe("useResizablePane", () => {
  beforeEach(() => localStorage.clear());

  it("starts at initial when no stored value", () => {
    const { result } = renderHook(() =>
      useResizablePane({ key: "k", min: 200, max: 480, initial: 264 })
    );
    expect(result.current.width).toBe(264);
  });

  it("clamps + persists on setWidth, and reset returns to initial", () => {
    const { result } = renderHook(() =>
      useResizablePane({ key: "sb", min: 200, max: 480, initial: 264 })
    );
    act(() => result.current.setWidth(9999));
    expect(result.current.width).toBe(480);
    expect(localStorage.getItem("sb")).toBe("480");
    act(() => result.current.reset());
    expect(result.current.width).toBe(264);
  });

  it("restores a previously stored width on mount", () => {
    localStorage.setItem("sb", "330");
    const { result } = renderHook(() =>
      useResizablePane({ key: "sb", min: 200, max: 480, initial: 264 })
    );
    expect(result.current.width).toBe(330);
  });
});

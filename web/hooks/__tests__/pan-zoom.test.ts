import { describe, it, expect } from "vitest";
import { zoomAt, fitView } from "@/hooks/use-pan-zoom";

describe("zoomAt", () => {
  it("keeps the cursor point fixed while scaling", () => {
    const t = { x: 0, y: 0, k: 1 };
    const next = zoomAt(t, { x: 100, y: 100 }, 2);
    expect(next.k).toBe(2);
    // world point under the cursor is unchanged: (cursor - x) / k constant
    expect((100 - t.x) / t.k).toBeCloseTo((100 - next.x) / next.k, 6);
  });

  it("clamps scale to bounds", () => {
    expect(zoomAt({ x: 0, y: 0, k: 1 }, { x: 0, y: 0 }, 100, [0.2, 4]).k).toBe(4);
    expect(zoomAt({ x: 0, y: 0, k: 1 }, { x: 0, y: 0 }, 0.0001, [0.2, 4]).k).toBe(0.2);
  });
});

describe("fitView", () => {
  it("centers content within the viewport", () => {
    const t = fitView(
      { minX: 0, minY: 0, maxX: 100, maxY: 100 },
      { width: 300, height: 300 },
      0
    );
    expect(t.k).toBeCloseTo(3, 6);
    // content center (50,50) maps to viewport center (150,150)
    expect(t.x + 50 * t.k).toBeCloseTo(150, 6);
    expect(t.y + 50 * t.k).toBeCloseTo(150, 6);
  });
});

import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";

import { buildScenario } from "@/lib/sim/scenario";
import { buildLoopPlan } from "@/lib/sim/loop";

/*
  Guards on the engine's defining property: it is fully deterministic given a
  seed and never reaches for Math.random (which would break replay/resume and
  make the SSE stream non-idempotent).
*/

const SIM_DIR = dirname(dirname(fileURLToPath(import.meta.url)));

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === "__tests__" ? [] : walk(p);
    return p.endsWith(".ts") ? [p] : [];
  });
}

describe("engine determinism", () => {
  it("contains no Math.random in lib/sim (replay-safety guard)", () => {
    // Match the call form so the rng.ts doc-comment ("never use Math.random")
    // doesn't trip the guard — only an actual Math.random(...) call counts.
    const offenders = walk(SIM_DIR).filter((f) =>
      /Math\.random\s*\(/.test(readFileSync(f, "utf8"))
    );
    expect(offenders).toEqual([]);
  });

  it("scenario is reproducible for the same (goal, seed)", () => {
    const a = buildScenario("Improve PPO on DoorKey", 123);
    const b = buildScenario("Improve PPO on DoorKey", 123);
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
  });

  it("loop plan is reproducible and obeys the stop policy", () => {
    const a = buildLoopPlan("goal", 6, 0.9, 2, 555);
    const b = buildLoopPlan("goal", 6, 0.9, 2, 555);
    expect(JSON.stringify(a)).toBe(JSON.stringify(b));
    // Terminal round honors the budget and best-metric is non-decreasing.
    expect(a.rounds.length).toBeLessThanOrEqual(6);
    for (let i = 1; i < a.rounds.length; i++) {
      expect(a.rounds[i].best_metric).toBeGreaterThanOrEqual(a.rounds[i - 1].best_metric);
    }
    expect(["goal_metric", "plateau", "max_rounds"]).toContain(a.stopReason);
  });
});

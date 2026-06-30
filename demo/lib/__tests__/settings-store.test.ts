import { beforeEach, describe, expect, it } from "vitest";

import {
  DEFAULT_BUDGET_KEY,
  getDefaultBudget,
  setDefaultBudget,
} from "@/lib/settings-store";

describe("settings-store: default budget", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns undefined when nothing is stored", () => {
    expect(getDefaultBudget()).toBeUndefined();
  });

  it("round-trips a positive budget", () => {
    setDefaultBudget(25);
    expect(getDefaultBudget()).toBe(25);
  });

  it("clears the stored value when set to undefined", () => {
    setDefaultBudget(25);
    setDefaultBudget(undefined);
    expect(getDefaultBudget()).toBeUndefined();
  });

  it("ignores non-positive or non-finite budgets", () => {
    setDefaultBudget(0);
    expect(getDefaultBudget()).toBeUndefined();
    setDefaultBudget(-5);
    expect(getDefaultBudget()).toBeUndefined();
    setDefaultBudget(Number.NaN);
    expect(getDefaultBudget()).toBeUndefined();
  });

  it("returns undefined for a corrupt stored value", () => {
    localStorage.setItem(DEFAULT_BUDGET_KEY, "not-a-number");
    expect(getDefaultBudget()).toBeUndefined();
  });
});

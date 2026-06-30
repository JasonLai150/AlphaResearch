// Client-only preferences, persisted to localStorage. There is no backend
// settings API (by design — see the web-pages spec), so these live entirely in
// the browser. Each accessor is SSR-safe (no-op without window) and defensive
// against corrupt stored values.

export const DEFAULT_BUDGET_KEY = "alpha.settings.defaultBudget";

function canUseStorage(): boolean {
  return typeof window !== "undefined" && !!window.localStorage;
}

/** The user's default budget for new runs, or undefined if unset/invalid. */
export function getDefaultBudget(): number | undefined {
  if (!canUseStorage()) return undefined;
  const raw = window.localStorage.getItem(DEFAULT_BUDGET_KEY);
  if (raw == null) return undefined;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

/** Store a positive budget; any non-positive/non-finite value clears it. */
export function setDefaultBudget(budget: number | undefined): void {
  if (!canUseStorage()) return;
  if (typeof budget === "number" && Number.isFinite(budget) && budget > 0) {
    window.localStorage.setItem(DEFAULT_BUDGET_KEY, String(budget));
  } else {
    window.localStorage.removeItem(DEFAULT_BUDGET_KEY);
  }
}

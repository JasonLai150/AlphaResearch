import type { CurrentUser } from "@/lib/types";

/*
  DEMO build: authentication is permanently disabled. The real app gates this on
  a Clerk publishable key; the mock has no backend and no Clerk, so it always
  runs as a fixed demo user. Kept as a named constant so the copied components
  that branch on `CLERK_ENABLED` / `clerk` keep compiling unchanged.
*/
export const CLERK_ENABLED = false as const;

export const DEMO_USER_ID = "demo";

export const DEMO_USER: CurrentUser = {
  name: "Aditya Billaume",
  handle: "adityabillaume",
  role: "Researcher",
  initials: "A",
};

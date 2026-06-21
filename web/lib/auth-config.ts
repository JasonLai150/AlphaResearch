import type { CurrentUser } from "@/lib/types";

/*
  Clerk is optional. When NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY is set, the app
  requires sign-in and sends the Clerk token to the API; otherwise it runs in a
  keyless dev mode as a fixed demo user. NEXT_PUBLIC_* is inlined at build, so
  this constant is stable across server and client.
*/
export const CLERK_ENABLED =
  typeof process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY === "string" &&
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY.length > 0;

export const DEMO_USER_ID = "demo";

export const DEMO_USER: CurrentUser = {
  name: "Demo User",
  handle: "demo",
  role: "Dev",
  initials: "D",
};

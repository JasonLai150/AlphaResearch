"use client";

import { createContext, useContext, type ReactNode } from "react";

import { DEMO_USER, DEMO_USER_ID } from "@/lib/auth-config";
import type { CurrentUser } from "@/lib/types";

interface AppAuth {
  userId: string;
  user: CurrentUser;
  getToken: () => Promise<string | undefined>;
  /** Whether Clerk auth is active (vs keyless demo mode). Always false here. */
  clerk: boolean;
}

// DEMO build: no Clerk. A fixed demo identity, no token. The real app swaps in a
// ClerkAuthProvider here; the mock has a single hard-coded provider.
const DEMO_VALUE: AppAuth = {
  userId: DEMO_USER_ID,
  user: DEMO_USER,
  getToken: async () => undefined,
  clerk: false,
};

const Ctx = createContext<AppAuth>(DEMO_VALUE);

export const useAppAuth = () => useContext(Ctx);

export function AppAuthProvider({ children }: { children: ReactNode }) {
  return <Ctx.Provider value={DEMO_VALUE}>{children}</Ctx.Provider>;
}

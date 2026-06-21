"use client";

import { createContext, useContext, type ReactNode } from "react";
import { useAuth, useUser } from "@clerk/nextjs";

import { CLERK_ENABLED, DEMO_USER, DEMO_USER_ID } from "@/lib/auth-config";
import type { CurrentUser } from "@/lib/types";

interface AppAuth {
  userId: string;
  user: CurrentUser;
  getToken: () => Promise<string | undefined>;
  /** Whether Clerk auth is active (vs keyless dev mode). */
  clerk: boolean;
}

const DEMO_VALUE: AppAuth = {
  userId: DEMO_USER_ID,
  user: DEMO_USER,
  getToken: async () => undefined,
  clerk: false,
};

const Ctx = createContext<AppAuth>(DEMO_VALUE);

export const useAppAuth = () => useContext(Ctx);

function DemoAuthProvider({ children }: { children: ReactNode }) {
  return <Ctx.Provider value={DEMO_VALUE}>{children}</Ctx.Provider>;
}

// Only mounted when Clerk is enabled (so these hooks always have a provider).
function ClerkAuthProvider({ children }: { children: ReactNode }) {
  const { userId, getToken } = useAuth();
  const { user } = useUser();

  const value: AppAuth = {
    userId: userId ?? DEMO_USER_ID,
    user: user
      ? {
          name: user.fullName ?? user.username ?? "User",
          handle:
            user.username ??
            user.primaryEmailAddress?.emailAddress?.split("@")[0] ??
            "user",
          role: "Member",
          initials: (
            user.firstName?.[0] ??
            user.username?.[0] ??
            "U"
          ).toUpperCase(),
        }
      : DEMO_USER,
    getToken: async () => (await getToken()) ?? undefined,
    clerk: true,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function AppAuthProvider({ children }: { children: ReactNode }) {
  return CLERK_ENABLED ? (
    <ClerkAuthProvider>{children}</ClerkAuthProvider>
  ) : (
    <DemoAuthProvider>{children}</DemoAuthProvider>
  );
}

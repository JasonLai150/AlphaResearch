import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { LandingHero } from "@/components/landing/landing-hero";

export const metadata: Metadata = {
  title:
    "AlphaResearch — Recursive Sandboxed Agents for Autonomous RL Research at Scale",
  description:
    "A lead agent scopes your research goal, recursively spawns sandboxed sub-agents that run RL experiments in parallel, and streams the results back — live.",
};

export default async function Page() {
  // Signed-in users skip the marketing page and land on the console. Guarded on
  // the server secret so keyless dev mode just renders the landing (no Clerk).
  if (process.env.CLERK_SECRET_KEY) {
    const { auth } = await import("@clerk/nextjs/server");
    const { userId } = await auth();
    if (userId) redirect("/app");
  }
  return <LandingHero />;
}

import type { Metadata } from "next";

import { LandingHero } from "@/components/landing/landing-hero";

export const metadata: Metadata = {
  title:
    "AlphaResearch — Recursive Sandboxed Agents for Autonomous RL Research at Scale",
  description:
    "A lead agent scopes your research goal, recursively spawns sandboxed sub-agents that run RL experiments in parallel, and streams the results back — live.",
};

// DEMO build: no server-side auth redirect — the marketing landing always
// renders; the hero CTA enters the console at /app.
export default function Page() {
  return <LandingHero />;
}

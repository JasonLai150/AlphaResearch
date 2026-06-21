import Link from "next/link";

import { Button } from "@/components/ui/button";
import { AlphaMark } from "@/components/landing/alpha-mark";

/*
  Minimal marketing nav — the brand mark + wordmark left, a single outline-pill
  "Sign in" right (DESIGN.md nav-bar: canvas bg, ink text, body-sm). The primary
  "Launch app" CTA lives in the hero, so the nav stays quiet.
*/
export function LandingNav() {
  return (
    <header className="absolute inset-x-0 top-0 z-20 flex items-center justify-between px-5 py-5 sm:px-8 sm:py-6">
      <Link
        href="/"
        className="flex items-center gap-2.5 text-ink transition-opacity hover:opacity-80"
      >
        <AlphaMark size={30} />
        <span className="text-sm tracking-[-0.01em]">AlphaResearch</span>
      </Link>
      <Button
        asChild
        variant="outline"
        size="sm"
        className="border-white/15 backdrop-blur-sm"
      >
        <Link href="/sign-in">Sign in</Link>
      </Button>
    </header>
  );
}

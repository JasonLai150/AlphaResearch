import Link from "next/link";

import { AlphaMark } from "@/components/landing/alpha-mark";
import { Button } from "@/components/ui/button";

// DEMO build: no real auth. This stands in for the Clerk sign-in screen — one
// click drops you straight into the console as the demo researcher.
export default function SignInPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-canvas px-6 py-12">
      <header className="flex flex-col items-center gap-3 text-center">
        <AlphaMark className="size-8 text-sunset" />
        <h1 className="text-lg font-medium text-ink">Alpha Research</h1>
        <p className="max-w-xs text-sm text-mute">
          Sign in to your research console
        </p>
      </header>
      <div className="flex w-full max-w-sm flex-col gap-3 rounded-2xl border border-hairline bg-canvas-card p-6">
        <Button asChild size="lg" className="w-full rounded-full">
          <Link href="/app">Continue as Demo Researcher</Link>
        </Button>
        <p className="text-center text-xs text-mute">
          This is an interactive demo — no account or password needed.
        </p>
      </div>
      <Link href="/" className="text-xs text-mute hover:text-ink">
        ← Back to home
      </Link>
    </div>
  );
}

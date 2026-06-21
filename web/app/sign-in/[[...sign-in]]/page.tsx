"use client";

import { SignIn } from "@clerk/nextjs";

import { CLERK_ENABLED } from "@/lib/auth-config";

export default function SignInPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-canvas px-6 py-12">
      <header className="text-center">
        <h1 className="text-lg font-medium text-ink">Alpha Research</h1>
        <p className="mt-1 text-sm text-mute">
          Sign in to your research console
        </p>
      </header>
      {CLERK_ENABLED ? (
        <SignIn fallbackRedirectUrl="/app" signUpUrl="/sign-up" />
      ) : (
        <p className="text-sm text-mute">
          Authentication is disabled in this environment.
        </p>
      )}
    </div>
  );
}

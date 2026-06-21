"use client";

import { SignIn } from "@clerk/nextjs";

import { CLERK_ENABLED } from "@/lib/auth-config";

export default function SignInPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-6">
      {CLERK_ENABLED ? (
        <SignIn />
      ) : (
        <p className="text-sm text-mute">Authentication is disabled in this environment.</p>
      )}
    </div>
  );
}

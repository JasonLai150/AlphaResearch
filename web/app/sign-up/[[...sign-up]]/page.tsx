"use client";

import { SignUp } from "@clerk/nextjs";

import { CLERK_ENABLED } from "@/lib/auth-config";

export default function SignUpPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-6">
      {CLERK_ENABLED ? (
        <SignUp />
      ) : (
        <p className="text-sm text-mute">Authentication is disabled in this environment.</p>
      )}
    </div>
  );
}

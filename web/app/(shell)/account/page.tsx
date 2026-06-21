"use client";

import { UserProfile } from "@clerk/nextjs";

import { useAppAuth } from "@/components/auth/app-auth";
import { PageHeader } from "@/components/page-header";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";

export default function AccountPage() {
  const { user, clerk } = useAppAuth();

  return (
    <>
      <PageHeader
        eyebrow="Account"
        title="Your account"
        description={
          clerk
            ? "Manage your profile, email, and security."
            : "Your identity in this development session."
        }
      />
      <div className="px-6 py-6">
        {clerk ? (
          // Clerk's full account-management surface; hash routing avoids needing
          // a catch-all route. Themed via <ClerkProvider appearance> in layout.
          <UserProfile routing="hash" />
        ) : (
          <div className="flex max-w-md flex-col gap-5 rounded-xl border border-hairline bg-canvas-card p-6">
            <div className="flex items-center gap-4">
              <Avatar className="size-12">
                <AvatarFallback className="text-base">
                  {user.initials}
                </AvatarFallback>
              </Avatar>
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="text-lg text-ink">{user.name}</span>
                <span className="text-[13px] text-mute">@{user.handle}</span>
              </div>
              <Badge
                variant="secondary"
                className="ml-auto uppercase tracking-wider"
              >
                {user.role}
              </Badge>
            </div>
            <p className="border-t border-hairline pt-4 text-[13px] leading-relaxed text-mute">
              Authentication is disabled (keyless dev mode). Configure Clerk to
              enable sign-in, real user profiles, and account management.
            </p>
          </div>
        )}
      </div>
    </>
  );
}

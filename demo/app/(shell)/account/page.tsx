"use client";

import { useAppAuth } from "@/components/auth/app-auth";
import { PageHeader } from "@/components/page-header";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";

export default function AccountPage() {
  const { user } = useAppAuth();

  return (
    <>
      <PageHeader
        eyebrow="Account"
        title="Your account"
        description="Your identity in this demo session."
      />
      <div className="px-6 py-6">
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
            This is an interactive demo running entirely in your browser — no
            backend, no sign-in. Everything you see is generated locally by a
            seeded simulation engine.
          </p>
        </div>
      </div>
    </>
  );
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";

import { Eyebrow } from "@/components/eyebrow";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CLERK_ENABLED } from "@/lib/auth-config";
import { getDefaultBudget, setDefaultBudget } from "@/lib/settings-store";
import { API_BASE } from "@/lib/types";
import { cn } from "@/lib/utils";

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-hairline px-5 py-3 last:border-b-0">
      <dt className="shrink-0 text-[13px] text-mute">{label}</dt>
      <dd
        className={cn(
          "truncate text-[13px] text-body",
          mono && "font-mono text-[12px]"
        )}
      >
        {value}
      </dd>
    </div>
  );
}

export default function SettingsPage() {
  // Load the stored budget on mount (client-only — avoids a hydration mismatch).
  const [budget, setBudget] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const b = getDefaultBudget();
    setBudget(b != null ? String(b) : "");
    setLoaded(true);
  }, []);

  function save() {
    const trimmed = budget.trim();
    const n = trimmed === "" ? undefined : Number(trimmed);
    if (n !== undefined && (!Number.isFinite(n) || n <= 0)) {
      toast.error("Enter a positive number, or leave it blank.");
      return;
    }
    setDefaultBudget(n);
    toast.success(
      n ? `Default budget set to ${n}.` : "Default budget cleared."
    );
  }

  return (
    <>
      <PageHeader
        eyebrow="Settings"
        title="Settings"
        description="Preferences are stored in this browser — there's no server-side settings store yet."
      />
      <div className="flex max-w-2xl flex-col gap-8 px-6 py-6">
        <section className="flex flex-col gap-3">
          <Eyebrow as="h2">Preferences</Eyebrow>
          <div className="flex flex-col gap-2 rounded-xl border border-hairline bg-canvas-card p-5">
            <label htmlFor="budget" className="text-sm text-ink">
              Default budget for new runs
            </label>
            <p className="text-[12px] text-mute">
              Applied when you start a new session. Leave blank to use the
              backend default.
            </p>
            <div className="flex gap-2 pt-1">
              <Input
                id="budget"
                inputMode="numeric"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
                placeholder="e.g. 25"
                className="max-w-[200px]"
                disabled={!loaded}
              />
              <Button variant="outline" onClick={save} disabled={!loaded}>
                Save
              </Button>
            </div>
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <Eyebrow as="h2">Environment</Eyebrow>
          <dl className="flex flex-col rounded-xl border border-hairline bg-canvas-card">
            <Row label="API base URL" value={API_BASE} mono />
            <Row
              label="Authentication"
              value={CLERK_ENABLED ? "Clerk (enabled)" : "Keyless dev mode"}
            />
          </dl>
        </section>

        <section className="flex flex-col gap-3">
          <Eyebrow as="h2">Account</Eyebrow>
          <Button asChild variant="outline" className="self-start">
            <Link href="/account">Manage your account</Link>
          </Button>
        </section>
      </div>
    </>
  );
}

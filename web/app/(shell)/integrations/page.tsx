"use client";

import {
  Box,
  Cloud,
  Database,
  RefreshCw,
  Server,
  ShieldCheck,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { useHealth, type HealthStatus } from "@/hooks/use-health";
import { CLERK_ENABLED } from "@/lib/auth-config";
import { API_BASE } from "@/lib/types";
import { cn } from "@/lib/utils";

type Tone = "positive" | "negative" | "neutral" | "muted";

const DOT: Record<Tone, string> = {
  positive: "bg-[#3fb950]",
  negative: "bg-destructive",
  neutral: "bg-breeze",
  muted: "bg-mute",
};

interface Integration {
  icon: LucideIcon;
  name: string;
  purpose: string;
  tone: Tone;
  status: string;
  detail?: string;
}

function healthDisplay(status: HealthStatus): { tone: Tone; status: string } {
  if (status === "ok") return { tone: "positive", status: "Connected" };
  if (status === "down") return { tone: "negative", status: "Unreachable" };
  return { tone: "muted", status: "Checking…" };
}

function IntegrationCard({ icon: Icon, name, purpose, tone, status, detail }: Integration) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-hairline bg-canvas-card p-5">
      <div className="flex items-center gap-3">
        <span className="flex size-9 items-center justify-center rounded-lg bg-canvas-soft text-body">
          <Icon className="size-4" aria-hidden />
        </span>
        <div className="flex flex-1 flex-col">
          <span className="text-sm text-ink">{name}</span>
          <span className="text-[12px] text-mute">{purpose}</span>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span
          className={cn("size-1.5 rounded-full", DOT[tone])}
          aria-hidden
        />
        <span className="text-[13px] text-body">{status}</span>
      </div>
      {detail ? (
        <p className="truncate font-mono text-[11px] text-mute" title={detail}>
          {detail}
        </p>
      ) : null}
    </div>
  );
}

export default function IntegrationsPage() {
  const { status, recheck } = useHealth();
  const health = healthDisplay(status);

  // Live / derived integrations — the frontend can actually verify these.
  const verified: Integration[] = [
    {
      icon: Server,
      name: "Backend API",
      purpose: "Orchestrator · sessions & SSE",
      tone: health.tone,
      status: health.status,
      detail: API_BASE,
    },
    {
      icon: ShieldCheck,
      name: "Authentication",
      purpose: "Clerk",
      tone: CLERK_ENABLED ? "positive" : "neutral",
      status: CLERK_ENABLED ? "Enabled" : "Keyless dev mode",
    },
  ];

  // Backend-managed services. The frontend has no status API for these, so they
  // are listed honestly as informational — not faked as connected.
  const managed: Integration[] = [
    { icon: Sparkles, name: "Anthropic Claude", purpose: "Lead & sub-agents", tone: "muted", status: "Managed on backend" },
    { icon: Box, name: "Modal", purpose: "Sub-agent sandboxes", tone: "muted", status: "Managed on backend" },
    { icon: Cloud, name: "Google Cloud Storage", purpose: "Artifacts", tone: "muted", status: "Managed on backend" },
    { icon: Database, name: "Redis", purpose: "State · event bus · queue", tone: "muted", status: "Managed on backend" },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Integrations"
        title="Integrations"
        description="Services this platform connects to. Backend reachability is checked live; service-level status is configured and managed on the backend."
        actions={
          <Button variant="outline" size="sm" onClick={() => recheck()}>
            <RefreshCw className="size-4" />
            Re-check
          </Button>
        }
      />
      <div className="flex flex-col gap-8 px-6 py-6">
        <section className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {verified.map((i) => (
            <IntegrationCard key={i.name} {...i} />
          ))}
        </section>
        <section className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {managed.map((i) => (
              <IntegrationCard key={i.name} {...i} />
            ))}
          </div>
        </section>
      </div>
    </>
  );
}

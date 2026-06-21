"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { SeriesChart } from "@/components/series-chart";
import { Eyebrow } from "@/components/eyebrow";
import type { SessionMetrics as Metrics } from "@/lib/sim/researcher";

/*
  In-chat long-term graphs: every researcher's reward curve overlaid (the
  headline RL metric), plus mean training loss and mean sample-efficiency across
  the population. Curves are aligned by training progress so different step
  budgets compare cleanly. Opened as a full-screen overlay from the right rail.
*/

const PALETTE = ["#ff7a17", "#a0c3ec", "#7c3aed", "#ffc285", "#c4b5fd", "#7d8187"];

function useMetrics(sid: string) {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    async function tick() {
      try {
        const res = await fetch(`/api/mock/sessions/${sid}/metrics`, { cache: "no-store" });
        if (!res.ok || cancelled) return;
        const m = (await res.json()) as Metrics;
        if (cancelled) return;
        setMetrics(m);
        const running = m.researchers.some(
          (r) => r.points.length > 0 && r.points.length < 18
        );
        if (running || m.researchers.every((r) => r.points.length === 0)) {
          timer = setTimeout(tick, 1500);
        }
      } catch {
        if (!cancelled) timer = setTimeout(tick, 2500);
      }
    }
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [sid]);
  return metrics;
}

/** Align researcher curves by point index (0..N) → one row per progress step. */
function rewardRows(m: Metrics) {
  const maxLen = Math.max(0, ...m.researchers.map((r) => r.points.length));
  const rows: Record<string, number>[] = [];
  for (let i = 0; i < maxLen; i++) {
    const row: Record<string, number> = { p: Math.round((i / Math.max(maxLen - 1, 1)) * 100) };
    for (const r of m.researchers) {
      if (i < r.points.length) row[r.label] = Number(r.points[i].reward.toFixed(3));
    }
    rows.push(row);
  }
  return rows;
}

function meanSeries(m: Metrics, pick: (p: { loss: number; efficiency: number }) => number) {
  const maxLen = Math.max(0, ...m.researchers.map((r) => r.points.length));
  const out: { step: number; value: number }[] = [];
  for (let i = 0; i < maxLen; i++) {
    const vals = m.researchers.filter((r) => i < r.points.length).map((r) => pick(r.points[i]));
    if (!vals.length) continue;
    out.push({ step: Math.round((i / Math.max(maxLen - 1, 1)) * 100), value: vals.reduce((a, b) => a + b, 0) / vals.length });
  }
  return out;
}

export function SessionMetrics({
  sessionId,
  onClose,
}: {
  sessionId: string;
  onClose: () => void;
}) {
  const m = useMetrics(sessionId);
  const hasData = m && m.researchers.some((r) => r.points.length > 0);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-canvas/95 backdrop-blur-sm">
      <header className="flex items-center justify-between border-b border-hairline px-5 py-3">
        <div className="flex flex-col">
          <Eyebrow as="h2">Long-term metrics</Eyebrow>
          <span className="text-[12px] text-mute">
            Reward, training loss, and sample-efficiency across all researchers
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close metrics"
          className="flex size-8 items-center justify-center rounded-lg border border-hairline text-mute transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X className="size-4" />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-6">
        {!hasData ? (
          <div className="mx-auto max-w-md rounded-xl border border-dashed border-hairline px-6 py-16 text-center text-[13px] text-mute">
            Metrics appear once the researchers start training.
          </div>
        ) : (
          <div className="mx-auto flex max-w-5xl flex-col gap-6">
            <section className="rounded-xl border border-hairline bg-canvas-card p-4">
              <div className="mb-3 flex items-center justify-between">
                <Eyebrow as="h3">{m!.metricName} by researcher</Eyebrow>
                <div className="flex flex-wrap gap-x-4 gap-y-1">
                  {m!.researchers.map((r, i) => (
                    <span key={r.id} className="flex items-center gap-1.5 text-[11px] text-mute">
                      <span className="inline-block size-2 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />
                      {r.label} · {r.kind}
                    </span>
                  ))}
                </div>
              </div>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={rewardRows(m!)} margin={{ top: 8, right: 16, bottom: 4, left: -12 }}>
                  <CartesianGrid stroke="#212327" vertical={false} />
                  <XAxis
                    dataKey="p"
                    stroke="#212327"
                    tick={{ fontSize: 10, fill: "#7d8187" }}
                    tickFormatter={(v) => `${v}%`}
                    tickLine={false}
                  />
                  <YAxis
                    domain={[0, 1]}
                    stroke="#212327"
                    tick={{ fontSize: 10, fill: "#7d8187" }}
                    tickLine={false}
                    width={34}
                  />
                  <Tooltip
                    contentStyle={{ background: "#191919", border: "1px solid #212327", borderRadius: 8, fontSize: 12 }}
                    labelStyle={{ color: "#7d8187" }}
                    labelFormatter={(v) => `${v}% of budget`}
                  />
                  {m!.researchers.map((r, i) => (
                    <Line
                      key={r.id}
                      type="monotone"
                      dataKey={r.label}
                      stroke={PALETTE[i % PALETTE.length]}
                      strokeWidth={r.outcome === "win" ? 2.5 : 1.5}
                      dot={false}
                      isAnimationActive={false}
                      connectNulls={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </section>

            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <section className="rounded-xl border border-hairline bg-canvas-card p-4">
                <Eyebrow as="h3">Mean training loss</Eyebrow>
                <SeriesChart points={meanSeries(m!, (p) => p.loss)} color="#a0c3ec" domain={[0, "auto"]} label="loss" stepLabel="progress" precision={3} height={200} />
              </section>
              <section className="rounded-xl border border-hairline bg-canvas-card p-4">
                <Eyebrow as="h3">Mean sample-efficiency</Eyebrow>
                <SeriesChart points={meanSeries(m!, (p) => p.efficiency)} color="#7c3aed" domain={[0, 1]} label="efficiency" stepLabel="progress" height={200} />
              </section>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

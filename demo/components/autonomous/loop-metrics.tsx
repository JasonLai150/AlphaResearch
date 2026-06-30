"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { SeriesChart } from "@/components/series-chart";
import { Eyebrow } from "@/components/eyebrow";
import type { LiveLoop } from "@/lib/sim/loop-store";

/*
  Cross-round long-term graphs for an autonomous loop: best metric per round
  (with target + baseline reference lines), plus mean training loss and sample-
  efficiency per round. These are the "long-term graphs inside the autonomous
  loop" — they grow one point per completed round.
*/
export function LoopMetrics({ loop }: { loop: LiveLoop }) {
  if (loop.rounds.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-hairline px-4 py-10 text-center text-[13px] text-mute">
        Cross-round metrics appear after the first round completes.
      </div>
    );
  }

  const bestData = loop.rounds.map((r) => ({
    round: r.round_index + 1,
    best: Number(r.best_metric.toFixed(3)),
  }));
  const lossData = loop.rounds.map((r) => ({ step: r.round_index + 1, value: r.loss }));
  const effData = loop.rounds.map((r) => ({ step: r.round_index + 1, value: r.efficiency }));

  return (
    <div className="flex flex-col gap-3">
      <section className="rounded-xl border border-hairline bg-canvas-card p-4">
        <div className="mb-2 flex items-baseline justify-between">
          <Eyebrow as="h3">Best {loop.metricName} per round</Eyebrow>
          <span className="font-mono text-[12px] text-ink">
            {loop.bestMetric.toFixed(3)}{" "}
            <span className="text-mute">/ target {loop.goalMetric.toFixed(2)}</span>
          </span>
        </div>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={bestData} margin={{ top: 8, right: 16, bottom: 4, left: -12 }}>
            <CartesianGrid stroke="#212327" vertical={false} />
            <XAxis
              dataKey="round"
              stroke="#212327"
              tick={{ fontSize: 10, fill: "#7d8187" }}
              tickLine={false}
              allowDecimals={false}
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
              labelFormatter={(v) => `round ${v}`}
              formatter={(v: number) => [v, "best"]}
            />
            <ReferenceLine y={loop.goalMetric} stroke="#7c3aed" strokeDasharray="4 4" />
            <ReferenceLine y={loop.baseline} stroke="#363a3f" strokeDasharray="2 4" />
            <Line type="monotone" dataKey="best" stroke="#ff7a17" strokeWidth={2.5} dot={{ r: 2.5, fill: "#ff7a17" }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </section>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <section className="rounded-xl border border-hairline bg-canvas-card p-4">
          <Eyebrow as="h3">Training loss per round</Eyebrow>
          <SeriesChart points={lossData} color="#a0c3ec" domain={[0, "auto"]} label="loss" stepLabel="round" height={180} />
        </section>
        <section className="rounded-xl border border-hairline bg-canvas-card p-4">
          <Eyebrow as="h3">Sample efficiency per round</Eyebrow>
          <SeriesChart points={effData} color="#7c3aed" domain={[0, 1]} label="efficiency" stepLabel="round" height={180} />
        </section>
      </div>
    </div>
  );
}

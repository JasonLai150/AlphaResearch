"use client";

import { RewardChart } from "@/components/metric-chart";
import { SeriesChart } from "@/components/series-chart";
import { Eyebrow } from "@/components/eyebrow";
import type { CurvePoint } from "@/lib/sim/types";

/*
  The three long-term training curves for one researcher: reward, training loss,
  and sample-efficiency. Reward uses the shared 0–1 RewardChart; loss/efficiency
  use the generic SeriesChart.
*/
function Panel({
  title,
  value,
  children,
}: {
  title: string;
  value?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-hairline bg-canvas-card p-4">
      <div className="flex items-baseline justify-between">
        <Eyebrow as="h3">{title}</Eyebrow>
        {value && <span className="font-mono text-[12px] text-ink">{value}</span>}
      </div>
      <div className="min-h-[132px]">{children}</div>
    </div>
  );
}

export function MetricGrid({
  points,
  metricName,
}: {
  points: CurvePoint[];
  metricName: string;
}) {
  const last = points.at(-1);
  if (!points.length) {
    return (
      <div className="rounded-xl border border-dashed border-hairline px-4 py-10 text-center text-[13px] text-mute">
        Metrics stream in once training starts…
      </div>
    );
  }
  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
      <Panel title={metricName} value={last ? last.reward.toFixed(3) : undefined}>
        <RewardChart points={points.map((p) => ({ step: p.step, reward: p.reward }))} height={132} />
      </Panel>
      <Panel title="Training loss" value={last ? last.loss.toFixed(3) : undefined}>
        <SeriesChart
          points={points.map((p) => ({ step: p.step, value: p.loss }))}
          color="#a0c3ec"
          domain={[0, "auto"]}
          label="loss"
        />
      </Panel>
      <Panel title="Sample efficiency" value={last ? last.efficiency.toFixed(3) : undefined}>
        <SeriesChart
          points={points.map((p) => ({ step: p.step, value: p.efficiency }))}
          color="#7c3aed"
          domain={[0, 1]}
          label="efficiency"
        />
      </Panel>
    </div>
  );
}

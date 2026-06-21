"use client";

import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/*
  A generic single-series line chart over training steps, styled to match the
  app's dark canvas. Used for the loss / efficiency / cross-round curves in the
  /view inspector and the autonomous-loops section. (Reward keeps using
  RewardChart for its fixed 0–1 domain.)
*/
export interface SeriesPoint {
  step: number;
  value: number;
}

export function SeriesChart({
  points,
  color = "#7c3aed",
  height = 132,
  domain,
  label = "value",
  stepLabel = "step",
  precision = 3,
}: {
  points: SeriesPoint[];
  color?: string;
  height?: number;
  /** Y-axis domain; defaults to auto. */
  domain?: [number | "auto", number | "auto"];
  label?: string;
  stepLabel?: string;
  precision?: number;
}) {
  if (!points || points.length === 0) return null;
  const data = points.map((p) => ({ step: p.step, value: Number(p.value.toFixed(precision)) }));
  if (data.length === 1) data.push({ ...data[0] });

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: -16 }}>
        <XAxis
          dataKey="step"
          stroke="#212327"
          tick={{ fontSize: 10, fill: "#7d8187" }}
          tickFormatter={(v) => (Number(v) >= 1000 ? `${Math.round(Number(v) / 1000)}k` : `${v}`)}
          tickLine={false}
        />
        <YAxis
          domain={domain ?? ["auto", "auto"]}
          stroke="#212327"
          tick={{ fontSize: 10, fill: "#7d8187" }}
          tickLine={false}
          width={34}
        />
        <Tooltip
          contentStyle={{
            background: "#191919",
            border: "1px solid #212327",
            borderRadius: 8,
            fontSize: 12,
          }}
          labelStyle={{ color: "#7d8187" }}
          itemStyle={{ color: "#fff" }}
          labelFormatter={(v) => `${stepLabel} ${Number(v).toLocaleString()}`}
          formatter={(v: number) => [v, label]}
        />
        <Line
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={2}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

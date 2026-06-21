"use client";

import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { MetricPoint } from "@/lib/types";

/** Reward-vs-steps chart. `spark` renders a compact, axis-less sparkline. */
export function RewardChart({
  points,
  height = 120,
  spark = false,
  color = "#ff7a17",
}: {
  points: MetricPoint[];
  height?: number;
  spark?: boolean;
  color?: string;
}) {
  if (!points || points.length < 2) return null;
  const data = points.map((p) => ({
    step: p.step,
    reward: Number(p.reward.toFixed(3)),
  }));

  if (spark) {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
          <Line
            type="monotone"
            dataKey="reward"
            stroke={color}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 10, bottom: 0, left: -16 }}>
        <XAxis
          dataKey="step"
          stroke="#212327"
          tick={{ fontSize: 10, fill: "#7d8187" }}
          tickFormatter={(v) => `${Math.round(Number(v) / 1000)}k`}
          tickLine={false}
        />
        <YAxis
          domain={[0, 1]}
          stroke="#212327"
          tick={{ fontSize: 10, fill: "#7d8187" }}
          tickLine={false}
          width={30}
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
          labelFormatter={(v) => `step ${Number(v).toLocaleString()}`}
          formatter={(v: number) => [v, "reward"]}
        />
        <Line
          type="monotone"
          dataKey="reward"
          stroke={color}
          strokeWidth={2}
          dot={{ r: 2, fill: color }}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

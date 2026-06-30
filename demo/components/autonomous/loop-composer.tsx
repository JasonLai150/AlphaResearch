"use client";

import { useState } from "react";
import { Infinity as InfinityIcon, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/eyebrow";

const PRESETS = [
  "Maximize PPO success on MiniGrid-DoorKey-8x8",
  "Improve SAC mean return on MuJoCo-HalfCheetah-v4",
  "Push DQN past 0.8 on MiniGrid-MultiRoom",
];

/*
  Starts an autonomous loop: a goal + a round budget + a target metric. The
  runner then re-spawns research rounds on its own until the goal is met, the
  budget is hit, or the metric plateaus.
*/
export function LoopComposer({ onCreated }: { onCreated: (lid: string) => void }) {
  const [goal, setGoal] = useState("");
  const [maxRounds, setMaxRounds] = useState(6);
  const [goalMetric, setGoalMetric] = useState(0.9);
  const [busy, setBusy] = useState(false);

  async function start() {
    const g = goal.trim();
    if (!g || busy) return;
    setBusy(true);
    try {
      const res = await fetch("/api/mock/loop", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal: g, max_rounds: maxRounds, goal_metric: goalMetric }),
      });
      if (!res.ok) throw new Error("could not start loop");
      const { loop_id } = (await res.json()) as { loop_id: string };
      onCreated(loop_id);
    } catch {
      toast.error("Couldn't start the loop.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-5 rounded-2xl border border-hairline bg-canvas-card p-6">
      <div className="flex items-center gap-2">
        <InfinityIcon className="size-5 text-sunset" aria-hidden />
        <h2 className="text-[15px] text-ink">Start an autonomous loop</h2>
      </div>

      <div className="flex flex-col gap-2">
        <Eyebrow as="label">Research goal</Eyebrow>
        <textarea
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          rows={3}
          placeholder="e.g. Maximize PPO success on MiniGrid-DoorKey-8x8, round after round, until it plateaus."
          className="w-full resize-none rounded-xl border border-hairline bg-canvas px-3.5 py-3 text-[14px] text-body outline-none placeholder:text-mute focus-visible:ring-2 focus-visible:ring-ring"
        />
        <div className="flex flex-wrap gap-1.5">
          {PRESETS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setGoal(p)}
              className="rounded-full border border-hairline px-2.5 py-1 text-[11px] text-mute transition-colors hover:border-canvas-mid hover:text-body"
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Eyebrow as="label">Round budget</Eyebrow>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={2}
              max={10}
              value={maxRounds}
              onChange={(e) => setMaxRounds(Number(e.target.value))}
              className="flex-1 accent-[#ff7a17]"
            />
            <span className="w-16 shrink-0 font-mono text-[13px] text-ink">
              {maxRounds} rounds
            </span>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <Eyebrow as="label">Target metric</Eyebrow>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={0.6}
              max={0.98}
              step={0.01}
              value={goalMetric}
              onChange={(e) => setGoalMetric(Number(e.target.value))}
              className="flex-1 accent-[#ff7a17]"
            />
            <span className="w-16 shrink-0 font-mono text-[13px] text-ink">
              {goalMetric.toFixed(2)}
            </span>
          </div>
        </div>
      </div>

      <Button onClick={start} disabled={!goal.trim() || busy} size="lg" className="rounded-full">
        {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <InfinityIcon className="size-4" aria-hidden />}
        Start loop
      </Button>
    </div>
  );
}

"use client";

import { useEffect, useRef } from "react";

import { useReducedMotion } from "@/hooks/use-reduced-motion";

/*
  A live node rendered as a mini RL simulation. `reward` animates an episode-
  reward curve being produced left→right; `grid` animates an agent stepping
  through a small gridworld to its goal. Both loop, and settle to a static frame
  under reduced-motion. Drawn on a tiny DPR-scaled canvas.
*/
export function SimCard({
  variant,
  label,
  agentId,
}: {
  variant: "reward" | "grid";
  label: string;
  agentId?: string;
}) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvasEl = ref.current;
    if (!canvasEl) return;
    const context = canvasEl.getContext("2d");
    if (!context) return;
    // Non-null aliases so the resize/loop closures keep the narrowed types.
    const canvas: HTMLCanvasElement = canvasEl;
    const ctx: CanvasRenderingContext2D = context;

    let w = 0;
    let h = 0;
    function resize() {
      const r = canvas.getBoundingClientRect();
      w = r.width;
      h = r.height;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    // Deterministic reward curve (logistic rise + faint texture).
    const N = 46;
    const curve = Array.from({ length: N }, (_, i) => {
      const xi = i / (N - 1);
      const base = 1 / (1 + Math.exp(-(xi - 0.45) * 9));
      const tex = (Math.sin(i * 12.9898) * 43758.545) % 1;
      return Math.max(0.04, Math.min(0.97, base * 0.9 + 0.06 + tex * 0.04));
    });

    // Gridworld staircase path from corner to goal.
    const G = 6;
    const path: [number, number][] = [[0, 0]];
    let gx = 0;
    let gy = 0;
    while (gx < G - 1 || gy < G - 1) {
      if (gx < G - 1 && (gy >= G - 1 || (gx + gy) % 2 === 0)) gx += 1;
      else gy += 1;
      path.push([gx, gy]);
    }

    function drawReward(p: number) {
      if (w <= 0 || h <= 0) return; // pre-layout frame — retry next tick
      ctx.clearRect(0, 0, w, h);
      const padX = 4;
      const padY = 6;
      const plotW = w - padX * 2;
      const plotH = h - padY * 2;
      const px = (i: number) => padX + (i / (N - 1)) * plotW;
      const py = (v: number) => padY + (1 - v) * plotH;
      const reveal = Math.max(1, Math.floor(p * (N - 1)));

      // Area fill.
      ctx.beginPath();
      ctx.moveTo(px(0), py(curve[0]));
      for (let i = 1; i <= reveal; i++) ctx.lineTo(px(i), py(curve[i]));
      ctx.lineTo(px(reveal), padY + plotH);
      ctx.lineTo(px(0), padY + plotH);
      ctx.closePath();
      const grad = ctx.createLinearGradient(0, padY, 0, padY + plotH);
      grad.addColorStop(0, "rgba(255,122,23,0.28)");
      grad.addColorStop(1, "rgba(255,122,23,0)");
      ctx.fillStyle = grad;
      ctx.fill();

      // Line.
      ctx.beginPath();
      ctx.moveTo(px(0), py(curve[0]));
      for (let i = 1; i <= reveal; i++) ctx.lineTo(px(i), py(curve[i]));
      ctx.strokeStyle = "rgba(255,160,90,0.95)";
      ctx.lineWidth = 1.4;
      ctx.stroke();

      // Frontier dot.
      ctx.beginPath();
      ctx.arc(px(reveal), py(curve[reveal]), 2.2, 0, Math.PI * 2);
      ctx.fillStyle = "#ffd9b0";
      ctx.fill();

      // Value readout.
      ctx.font = "10px ui-monospace, SFMono-Regular, Menlo, monospace";
      ctx.fillStyle = "rgba(218,219,223,0.85)";
      ctx.textAlign = "right";
      ctx.fillText(curve[reveal].toFixed(2), w - 4, padY + 8);
    }

    function drawGrid(step: number) {
      // Guard the pre-layout frame: a 0-size canvas makes `cell` negative, and a
      // negative arc radius throws — which would kill this card's rAF loop before
      // the ResizeObserver ever delivers the real size.
      if (w <= 0 || h <= 0) return;
      ctx.clearRect(0, 0, w, h);
      const cell = Math.min((h - 4) / G, (w - 4) / G);
      const ox = (w - cell * G) / 2;
      const oy = (h - cell * G) / 2;

      // Grid lines.
      ctx.strokeStyle = "rgba(255,255,255,0.1)";
      ctx.lineWidth = 1;
      for (let i = 0; i <= G; i++) {
        ctx.beginPath();
        ctx.moveTo(ox + i * cell, oy);
        ctx.lineTo(ox + i * cell, oy + G * cell);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(ox, oy + i * cell);
        ctx.lineTo(ox + G * cell, oy + i * cell);
        ctx.stroke();
      }

      const cx = (c: number) => ox + (c + 0.5) * cell;
      const cy = (c: number) => oy + (c + 0.5) * cell;

      // Goal.
      const goal = path[path.length - 1];
      ctx.fillStyle = "rgba(255,122,23,0.85)";
      ctx.fillRect(ox + goal[0] * cell + 1.5, oy + goal[1] * cell + 1.5, cell - 3, cell - 3);

      // Fading trail.
      for (let i = 0; i <= step; i++) {
        const [tx, ty] = path[i];
        const age = step - i;
        ctx.fillStyle = `rgba(160,195,236,${Math.max(0.12, 0.6 - age * 0.08)})`;
        ctx.beginPath();
        ctx.arc(cx(tx), cy(ty), cell * 0.18, 0, Math.PI * 2);
        ctx.fill();
      }

      // Agent.
      const [ax, ay] = path[Math.min(step, path.length - 1)];
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.arc(cx(ax), cy(ay), cell * 0.26, 0, Math.PI * 2);
      ctx.fill();
    }

    let raf = 0;
    if (reduced) {
      if (variant === "reward") drawReward(1);
      else drawGrid(path.length - 1);
    } else {
      const loop = (now: number) => {
        if (variant === "reward") {
          drawReward(Math.min(1, (now / 3600) % 1.3));
        } else {
          const total = path.length + 3;
          const cyc = Math.floor(now / 280) % total;
          drawGrid(Math.min(cyc, path.length - 1));
        }
        raf = window.requestAnimationFrame(loop);
      };
      raf = window.requestAnimationFrame(loop);
    }

    return () => {
      window.cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [variant, reduced]);

  return (
    <div className="w-[14rem] overflow-hidden rounded-lg border border-hairline bg-canvas-card/75 shadow-[0_8px_30px_rgba(0,0,0,0.45)] backdrop-blur-md">
      <div className="flex items-center gap-2 border-b border-hairline/70 px-3 py-2">
        <span className="size-1.5 rounded-full bg-breeze shadow-[0_0_8px_rgba(160,195,236,0.9)]" />
        <span className="font-mono text-[11px] tracking-tight text-body">{label}</span>
        <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.12em] text-mute">
          {variant === "reward" ? "eval" : "sim"}
        </span>
      </div>
      <div className="px-3 py-2">
        <canvas ref={ref} className="block h-[68px] w-full" />
        {agentId && (
          <p className="mt-1 truncate font-mono text-[10px] tracking-tight text-mute">
            {agentId}
          </p>
        )}
      </div>
    </div>
  );
}

"use client";

import { useEffect, useMemo, useRef } from "react";

import { buildAgentTree } from "@/lib/landing/graph";
import { StreamCard } from "@/components/landing/live-nodes/stream-card";
import { SimCard } from "@/components/landing/live-nodes/sim-card";

/*
  The live agent tree. A <canvas> draws the skeleton — edges drawing outward ring
  by ring, glowing nodes, the α root, and "signal" packets streaming the edges
  (the SSE flowing between agents). The promoted card nodes (stream / sim) are
  positioned over their node coordinates as crisp DOM cards (lg+ only; the canvas
  still anchors them with a glow so the tree reads on mobile too). Time-based, so
  the reveal flows into the idle loop; honors prefers-reduced-motion.
*/

const STOPS = [
  [255, 122, 23],
  [124, 58, 237],
  [160, 195, 236],
];

const RING_MS = 320;
const STAGGER_MS = 40;
const INTRO_MS = 200;
const EDGE_MS = 520;
const PARALLAX = 10;

const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);

function ramp(f: number): [number, number, number] {
  const s = clamp(f) * (STOPS.length - 1);
  const i = Math.min(STOPS.length - 2, Math.floor(s));
  const k = s - i;
  const a = STOPS[i];
  const b = STOPS[i + 1];
  return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
}
const rgba = (c: [number, number, number], a: number) =>
  `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;

export function AgentTreeField({ className }: { className?: string }) {
  const tree = useMemo(() => buildAgentTree({ maxDepth: 3, rootBreadth: 4 }), []);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const cards = tree.nodes.filter((n) => n.kind === "stream" || n.kind === "sim");

  useEffect(() => {
    const canvasEl = canvasRef.current;
    const wrapEl = wrapRef.current;
    if (!canvasEl || !wrapEl) return;
    const context = canvasEl.getContext("2d");
    if (!context) return;
    const canvas: HTMLCanvasElement = canvasEl;
    const wrap: HTMLDivElement = wrapEl;
    const ctx: CanvasRenderingContext2D = context;

    const { nodes, edges, maxDepth } = tree;
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const start = new Map<string, number>();
    for (const n of nodes) {
      start.set(n.id, INTRO_MS + n.depth * RING_MS + (n.spawnOrder % 6) * STAGGER_MS);
    }
    const isCard = (k: string) => k === "stream" || k === "sim";

    let w = 0;
    let h = 0;
    let unit = 1;
    function resize() {
      const r = wrap.getBoundingClientRect();
      w = r.width;
      h = r.height;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      unit = Math.max(0.6, Math.min(w, h) / 460);
    }
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);

    const reduce =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let offX = 0;
    let offY = 0;
    let tgtX = 0;
    let tgtY = 0;
    const onMove = (e: PointerEvent) => {
      const r = wrap.getBoundingClientRect();
      tgtX = (((e.clientX - r.left) / r.width) * 2 - 1) * PARALLAX;
      tgtY = (((e.clientY - r.top) / r.height) * 2 - 1) * PARALLAX;
    };
    if (!reduce) window.addEventListener("pointermove", onMove, { passive: true });

    const pos = (n: { x: number; y: number }) =>
      [n.x * w + offX, n.y * h + offY] as const;

    function render(t: number) {
      offX += (tgtX - offX) * 0.06;
      offY += (tgtY - offY) * 0.06;
      ctx.clearRect(0, 0, w, h);

      // ── Edges + signal packets (additive) ──
      ctx.globalCompositeOperation = "lighter";
      for (const e of edges) {
        const prog = easeOut(clamp((t - (start.get(e.to) ?? 0)) / EDGE_MS));
        if (prog <= 0) continue;
        const from = byId.get(e.from);
        const to = byId.get(e.to);
        if (!from || !to) continue;
        const [fx, fy] = pos(from);
        const [tx, ty] = pos(to);
        const ex = fx + (tx - fx) * prog;
        const ey = fy + (ty - fy) * prog;
        const c = ramp(e.depth / maxDepth);
        const flow = 0.5 + 0.5 * Math.sin(t * 0.0019 - e.order);

        ctx.strokeStyle = rgba(c, 0.05 + 0.05 * flow);
        ctx.lineWidth = 2.4 * unit;
        ctx.beginPath();
        ctx.moveTo(fx, fy);
        ctx.lineTo(ex, ey);
        ctx.stroke();

        ctx.strokeStyle = rgba(c, (0.3 + 0.2 * flow) * prog);
        ctx.lineWidth = 0.9 * unit;
        ctx.stroke();

        // SSE packet travelling the revealed portion.
        const f = (t * 0.00026 + e.order * 0.17) % 1;
        if (f <= prog) {
          const ppx = fx + (tx - fx) * f;
          const ppy = fy + (ty - fy) * f;
          const g = ctx.createRadialGradient(ppx, ppy, 0, ppx, ppy, 3 * unit);
          g.addColorStop(0, rgba([255, 226, 196], 0.95));
          g.addColorStop(1, rgba(c, 0));
          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.arc(ppx, ppy, 3 * unit, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      // Node halos (additive) — root burns warmest; card nodes get a wider anchor.
      for (const n of nodes) {
        const appear = (start.get(n.id) ?? 0) + (n.depth === 0 ? 0 : EDGE_MS * 0.5);
        const np = easeOut(clamp((t - appear) / 440));
        if (np <= 0) continue;
        const pulse = 0.55 + 0.45 * Math.sin(t * 0.0016 + n.spawnOrder);
        const [px, py] = pos(n);
        const c = n.depth === 0 ? ([255, 150, 60] as [number, number, number]) : ramp(n.depth / maxDepth);
        const base = n.depth === 0 ? 30 : isCard(n.kind) ? 22 : 12 - n.depth * 1.5;
        const haloR = base * unit * (0.65 + 0.35 * pulse) * np;
        const g = ctx.createRadialGradient(px, py, 0, px, py, Math.max(2, haloR));
        g.addColorStop(0, rgba(c, (n.depth === 0 ? 0.5 : 0.4) * np));
        g.addColorStop(1, rgba(c, 0));
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(px, py, Math.max(2, haloR), 0, Math.PI * 2);
        ctx.fill();
      }

      // Crisp cores (source-over). Card nodes are drawn by the DOM cards.
      ctx.globalCompositeOperation = "source-over";
      for (const n of nodes) {
        if (n.depth === 0 || isCard(n.kind)) continue;
        const appear = (start.get(n.id) ?? 0) + EDGE_MS * 0.5;
        const np = easeOut(clamp((t - appear) / 440));
        if (np <= 0) continue;
        const pulse = 0.55 + 0.45 * Math.sin(t * 0.0016 + n.spawnOrder);
        const [px, py] = pos(n);
        const c = ramp(n.depth / maxDepth);
        const half = Math.max(1, (3.6 - n.depth * 0.5) * (0.8 + 0.35 * pulse) * np * unit);
        ctx.fillStyle = rgba(c, 0.92 * np);
        ctx.beginPath();
        ctx.roundRect(px - half, py - half, half * 2, half * 2, half * 0.5);
        ctx.fill();
        ctx.strokeStyle = rgba([255, 255, 255], 0.22 * np);
        ctx.lineWidth = 0.6 * unit;
        ctx.stroke();
      }

      // Root α.
      const root = nodes.find((n) => n.depth === 0);
      if (root) {
        const np = easeOut(clamp((t - (start.get(root.id) ?? 0)) / 440));
        const [px, py] = pos(root);
        ctx.fillStyle = rgba([255, 255, 255], 0.96 * np);
        ctx.font = `${Math.round(20 * unit)}px ui-sans-serif, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("α", px, py + unit);
      }
    }

    let raf = 0;
    if (reduce) {
      render(INTRO_MS + maxDepth * RING_MS + EDGE_MS + 4000);
    } else {
      const loop = (now: number) => {
        render(now);
        raf = window.requestAnimationFrame(loop);
      };
      raf = window.requestAnimationFrame(loop);
    }

    return () => {
      window.cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("pointermove", onMove);
    };
  }, [tree]);

  return (
    <div ref={wrapRef} className={className}>
      <canvas ref={canvasRef} className="block size-full" />
      {cards.map((n) => (
        <div
          key={n.id}
          className="landing-rise absolute hidden lg:block"
          style={{
            left: `${n.x * 100}%`,
            top: `${n.y * 100}%`,
            transform: "translate(-50%, -50%)",
            animationDelay: `${INTRO_MS + n.depth * RING_MS}ms`,
          }}
        >
          {n.kind === "stream" ? (
            <StreamCard
              agentId={n.agentId ?? "agent"}
              lines={n.streamLines ?? []}
              delayMs={n.depth * 200}
            />
          ) : (
            <SimCard variant={n.sim ?? "reward"} label={n.simLabel ?? ""} agentId={n.agentId} />
          )}
        </div>
      ))}
    </div>
  );
}

import type { CurvePoint, StrategySpec } from "@/lib/sim/types";

/*
  Deterministic, code-generated artifact visuals — no image files, no network.
  These produce `data:image/svg+xml` URIs so the existing right-rail <img> (and
  the /view gallery) render them unchanged. Richer interactive visuals (animated
  gridworld) live in components/sim/* and are driven from the same Scenario.
*/

const C = {
  bg: "#191919",
  grid: "#212327",
  axis: "#363a3f",
  line: "#ff7a17",
  line2: "#7c3aed",
  text: "#7d8187",
};

function encode(svg: string): string {
  // Compact + URL-encode so it's a valid <img src>.
  return "data:image/svg+xml," + encodeURIComponent(svg.replace(/\s+/g, " ").trim());
}

function path(points: CurvePoint[], pick: (p: CurvePoint) => number, w: number, h: number, pad: number): string {
  const xs = points.map((_, i) => pad + (i / (points.length - 1)) * (w - 2 * pad));
  const ys = points.map((p) => {
    const v = pick(p); // assumed 0..~1.2
    return h - pad - Math.max(0, Math.min(1, v)) * (h - 2 * pad);
  });
  return xs.map((x, i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${ys[i].toFixed(1)}`).join(" ");
}

/** Reward-vs-step training plot. kind:"plot" → rendered as an image. */
export function rewardPlotUri(spec: StrategySpec): string {
  const w = 320;
  const h = 168;
  const pad = 16;
  const reward = path(spec.points, (p) => p.reward, w, h, pad);
  const grid = [0.25, 0.5, 0.75]
    .map((g) => {
      const y = h - pad - g * (h - 2 * pad);
      return `<line x1="${pad}" y1="${y}" x2="${w - pad}" y2="${y}" stroke="${C.grid}" stroke-width="1"/>`;
    })
    .join("");
  const final = spec.points[spec.points.length - 1].reward.toFixed(2);
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">
      <rect width="${w}" height="${h}" fill="${C.bg}"/>
      ${grid}
      <line x1="${pad}" y1="${h - pad}" x2="${w - pad}" y2="${h - pad}" stroke="${C.axis}" stroke-width="1"/>
      <path d="${reward}" fill="none" stroke="${C.line}" stroke-width="2"/>
      <text x="${w - pad}" y="${pad + 4}" fill="${C.text}" font-family="monospace" font-size="11" text-anchor="end">reward ${final}</text>
      <text x="${pad}" y="${h - 4}" fill="${C.text}" font-family="monospace" font-size="10">0</text>
      <text x="${w - pad}" y="${h - 4}" fill="${C.text}" font-family="monospace" font-size="10" text-anchor="end">${(spec.steps / 1000).toFixed(0)}k steps</text>
    </svg>`;
  return encode(svg);
}

/** A small gridworld snapshot with the agent's path key→door. */
export function gridworldUri(spec: StrategySpec, n = 8): string {
  const size = 168;
  const cell = size / n;
  // Deterministic "solved" path derived from the spec id char codes.
  const seed = spec.id.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
  const cells: string[] = [];
  for (let y = 0; y < n; y++)
    for (let x = 0; x < n; x++) {
      const wall = (x === 0 || y === 0 || x === n - 1 || y === n - 1 || ((x + y + seed) % 7 === 0 && x > 1 && x < n - 2));
      cells.push(
        `<rect x="${x * cell}" y="${y * cell}" width="${cell - 1}" height="${cell - 1}" fill="${wall ? "#212327" : "#0f0f0f"}"/>`
      );
    }
  // path from top-left to bottom-right (illustrative)
  const pts: string[] = [];
  let cx = 1, cy = 1;
  for (let i = 0; i < n + 4; i++) {
    pts.push(`${cx * cell + cell / 2},${cy * cell + cell / 2}`);
    if (cx < n - 2 && (i + seed) % 2 === 0) cx++;
    else if (cy < n - 2) cy++;
    else if (cx < n - 2) cx++;
  }
  const key = `<circle cx="${2 * cell + cell / 2}" cy="${(n - 3) * cell + cell / 2}" r="${cell / 4}" fill="#ffc285"/>`;
  const door = `<rect x="${(n - 2) * cell + cell / 4}" y="${(n - 2) * cell + cell / 4}" width="${cell / 2}" height="${cell / 2}" fill="#7c3aed"/>`;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
      <rect width="${size}" height="${size}" fill="${C.bg}"/>
      ${cells.join("")}
      ${key}${door}
      <polyline points="${pts.join(" ")}" fill="none" stroke="${C.line}" stroke-width="2" stroke-linejoin="round" opacity="0.9"/>
      <circle cx="${pts[pts.length - 1].split(",")[0]}" cy="${pts[pts.length - 1].split(",")[1]}" r="${cell / 4}" fill="${C.line}"/>
    </svg>`;
  return encode(svg);
}

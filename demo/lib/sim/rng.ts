/*
  Seeded pseudo-random number generator. The demo is fully deterministic given a
  seed — same seed reproduces the same run, byte for byte. We NEVER use
  Math.random anywhere in the simulation (a test guard enforces this), so runs
  are replayable and the SSE stream can resume/re-derive identical state.
*/

/** mulberry32 — a tiny, fast, decent-quality 32-bit PRNG. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return function next() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Stable string → 32-bit seed (FNV-1a). */
export function seedFromString(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

export type Rng = () => number;

/** Uniform float in [min, max). */
export function uniform(rng: Rng, min: number, max: number): number {
  return min + (max - min) * rng();
}

/** Integer in [min, max] inclusive. */
export function int(rng: Rng, min: number, max: number): number {
  return Math.floor(uniform(rng, min, max + 1));
}

/** Pick one element. */
export function pick<T>(rng: Rng, arr: readonly T[]): T {
  return arr[Math.floor(rng() * arr.length)];
}

/** Fisher–Yates shuffle (returns a new array). */
export function shuffle<T>(rng: Rng, arr: readonly T[]): T[] {
  const out = arr.slice();
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** Take the first `n` of a seeded shuffle — sampling without replacement. */
export function sample<T>(rng: Rng, arr: readonly T[], n: number): T[] {
  return shuffle(rng, arr).slice(0, Math.min(n, arr.length));
}

/** Approx. standard-normal via Box–Muller; scaled to (mean, sd). */
export function gaussian(rng: Rng, mean = 0, sd = 1): number {
  const u = Math.max(rng(), 1e-9);
  const v = rng();
  const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  return mean + sd * z;
}

/** A jittered copy of `base` within ±spread (absolute). */
export function jitter(rng: Rng, base: number, spread: number): number {
  return base + uniform(rng, -spread, spread);
}

/** Clamp to a range. */
export function clamp(x: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, x));
}

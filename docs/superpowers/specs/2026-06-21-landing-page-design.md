# Landing Page — "Seed of the Recursion"

**Date:** 2026-06-21
**Status:** Approved, in implementation
**Pitch:** *Recursive Sandboxed Agents for Autonomous RL Research at Scale*

## Goal

A single, cinematic, full-viewport hero landing page at `/` whose signature
motif is the **α logo as the root agent** — a living recursive agent graph
blooms out of it (a lead node spawning sandboxed sub-agents, recursively),
literally rendering the pitch. Built on the existing xAI-inspired design system
(`/DESIGN.md`): near-black canvas, Geist 400 display with negative tracking,
Geist Mono uppercase eyebrows, white outline pills — pushed to a "maximal"
register with bold accent glows and motion that the rest of the system holds in
reserve.

## Routing

- `/` becomes the **public landing page**. A server component checks Clerk auth;
  signed-in users are redirected to `/app`. Guarded on `CLERK_SECRET_KEY` so
  keyless dev mode skips the check and always shows the landing.
- The existing research console (`app/page.tsx`) **relocates to `app/app/page.tsx`**
  (route `/app`), code unchanged (it uses `@/` aliases).
- `middleware.ts`: add `/` to the public matcher; `/app` and all else stay gated.
- `sign-in`'s `fallbackRedirectUrl` → `/app` (post-sign-in lands on the console).
- Sign-out already returns to `/` (the landing) via `afterSignOutUrl="/"`.

## Components (modular, no new dependencies)

```
app/page.tsx                         server: auth-redirect + metadata + <LandingHero/>
app/icon.svg                         α favicon (browser tab → α)
app/app/page.tsx                     relocated console (unchanged)
components/landing/landing-hero.tsx  composition: atmosphere + field + nav + content
components/landing/agent-graph-field.tsx  animated <canvas> recursive graph
components/landing/landing-nav.tsx   α mark + wordmark + "Sign in" pill
components/landing/alpha-mark.tsx    reusable α-in-rounded-square SVG mark
lib/landing/graph.ts                 PURE buildGraph(depth, breadth) → {nodes, edges}
```

Separating `graph.ts` (pure data) from `agent-graph-field.tsx` (canvas render)
keeps the recursion logic unit-testable without a DOM/canvas.

## Visual layers (back → front)

1. **Atmosphere** — `#0a0a0a` with slow-drifting radial glows in sunset
   `#ff7a17` and dusk `#7c3aed` (low opacity). The accent palette, used boldly.
2. **Recursive agent field** — full-bleed `<canvas>`, dimmed + vignetted. α at
   center is the root; edges recursively spawn rounded-square "sandbox" nodes.
   Load: edges draw outward in staggered depth waves. Idle: nodes pulse, edges
   flow (dashed signal), subtle pointer parallax. `prefers-reduced-motion` →
   one composed static frame, no loop.
3. **Foreground** (centered): nav · eyebrow `α · AUTONOMOUS RESEARCH PLATFORM` ·
   H1 (pitch, with a single sunset→dusk gradient-text accent on "autonomous RL
   research") · lead line · white-filled `Launch app` pill → `/app` + a quiet
   `View a live run →` text link.

## α mark

A geometric α inscribed in a softly-rounded square — the glyph *and* the
sandbox in one mark. Reused as nav logo, hero graph root, and `app/icon.svg`.

## Motion / accessibility

- Hand-rolled: CSS keyframes for foreground reveal + a single `requestAnimationFrame`
  loop for the canvas field. No framer-motion, no new deps.
- Honors `prefers-reduced-motion` (static frame, content visible immediately).
- Responsive: H1 scales ~96px → ~40px on mobile (per DESIGN.md breakpoints).
- Self-hosted Geist only — no external/runtime font fetch.

## Testing

- `lib/landing/__tests__/graph.test.ts` — `buildGraph` shape: child counts,
  depth bound, deterministic, no orphan edges.
- `components/landing/__tests__/landing-hero.test.tsx` — renders the headline,
  the `Launch app` CTA pointing at `/app`, and the nav sign-in link.

## Assumptions

- Console moves to `/app`; `/` redirects signed-in users there.
- One gradient-text accent on the headline is enough "maximal" without betraying
  the system's restraint elsewhere.
- Canvas (not SVG) for the field — luminous additive-blend glow + smooth parallax.

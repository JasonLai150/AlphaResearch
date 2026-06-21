# Web app pages — design

**Date:** 2026-06-21
**Branch:** `worktree-web-pages` (isolated worktree off clean `main` @ d9a768b)
**Status:** Approved, ready for implementation

## Problem

The sidebar advertises "Overview", "Integrations", "Projects", "Settings", and a
user profile, but none of them are real pages:

- `Overview` / `Integrations` / `Projects` only flip a local `activeNav` `useState`
  highlight (`app-sidebar.tsx`) — no route, no content change.
- `Settings` is a `<button>` with **no `onClick`** — completely dead.
- The user-profile row is a dead button in keyless mode; only Clerk mode's
  `<UserButton>` does anything.

The only real routes are `/` (the chat console), `/sign-in`, `/sign-up`.

## Goal

Turn each advertised destination into a real, navigable page that renders cleanly
with real data where it exists. **Frontend-only** — no new backend endpoints.

## Constraints (verified against the codebase)

- **Dark-only design system** (`globals.css`: "no light counterpart"). → No theme toggle.
- **Backend exposes only** session endpoints + `GET /health` (returns `{"ok": true}`,
  liveness only — no per-service status, no settings/projects/integrations/user APIs).
- **Session shape** (`WireSession`): `id, user_id, goal, mode, status, created_at,
  root_job_id`. Enough for real aggregation/grouping.
- **Auth context** (`useAppAuth`): `user {name, handle, role, initials}`, `clerk` bool;
  Clerk's `<UserProfile>` available when enabled.

## Coordination note (concurrent work)

A separate, **active** effort on `feat/landing-page` is moving the console from `/`
to `/app` to free `/` for a marketing landing page (uncommitted WIP in the primary
checkout). Per the user's decision, this work is **independent on clean `main`**:
console stays at `/`, new pages at top-level routes (`/overview`, …). If the
landing-page restructure lands, whoever merges reconciles the route prefix (likely
nesting these pages under `/app`). We do not touch the landing-page working tree.

## Architecture

A Next.js **route group** `app/(shell)/` (parentheses → no URL segment) holds the new
pages under a `layout.tsx` that renders a shared **AppShell**: the persistent sidebar +
mobile drawer + a scrollable `<main>` for page content. The console at `app/page.tsx`
is left untouched (it keeps its bespoke 3-pane layout + right rail).

`AppSidebar` stays the single source of truth for navigation, used by both the console
and the shell. Its nav becomes real:

- Nav items, `Settings`, and the user row → `next/link` with active state via
  `usePathname()` (replacing the dead `setActiveNav`).
- Logo → `/`. Session rows → `/?s=<id>`.

New small modules (single responsibility, all well under 800 lines):

- `lib/settings-store.ts` — localStorage-backed client prefs.
- `hooks/use-health.ts` — pings `GET /health` for backend reachability.
- `lib/session-stats.ts` — pure aggregation helpers for Overview.

## Pages

| Route | Page | Content (data source) |
|---|---|---|
| `/` | Console | Unchanged. |
| `/overview` | Overview | Stat cards (total / running / done / failed from `sessions[].status`) + recent-sessions list (→ `/?s=<id>`); loading skeletons + empty state. |
| `/integrations` | Integrations | **Live:** backend reachability (`GET /health`) + API URL; auth mode (`CLERK_ENABLED`). **Informational** cards (honestly labeled "managed on backend", neutral status — no faked green checks): Modal, GCS, Redis, W&B, Browserbase, Claude. |
| `/projects` | Projects | Sessions grouped by `mode` (the only natural grouping field), each → console; empty/loading. Lower priority but no longer a dead nav item. |
| `/settings` | Settings | One real, persisted+consumed pref: **default budget** for new runs (localStorage → fed into `createSession`). Read-only env info (API URL, auth mode). Link to account. No theme toggle. |
| `/account` | User | Keyless → profile card from `useAppAuth`. Clerk → embed `<UserProfile>` (real account management). |

## Cross-cutting

- **States:** every page handles loading (skeletons matching existing style), empty, and
  error, consistent with the existing `error.tsx`.
- **Mobile:** AppShell reuses the existing `Sheet` drawer pattern from the console.
- **Tests:** Vitest + RTL render tests matching `components/__tests__/`: Overview
  stats/empty, Integrations cards, Settings persistence, sidebar active-nav from pathname.
- **Verification:** dev server + browser-preview tools load every route, check
  console/network for errors, screenshot each as proof.

## Out of scope (YAGNI)

No new backend endpoints; no server-side settings persistence; no theme system; no real
per-service health for Modal/GCS/etc. (backend doesn't expose it — we won't fake status);
no changes to the console or the landing-page work.

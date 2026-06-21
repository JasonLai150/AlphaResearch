import { AgentTreeField } from "@/components/landing/agent-tree-field";
import { AlphaMark } from "@/components/landing/alpha-mark";
import { LandingNav } from "@/components/landing/landing-nav";
import { LaunchGate } from "@/components/landing/launch-gate";

/*
  The hero: a full-viewport "living research console". The pitch sits on the
  left; the live agent tree owns the right — a lead agent recursively spawning
  sandboxed sub-agents, with signal packets streaming the edges, some nodes
  rendering live SSE token feeds, and others running mini RL simulations. Drifting
  accent atmosphere behind it all. On small screens it stacks (pitch over the
  tree) and the cards step aside so the canvas tree carries the motif alone.
*/
export function LandingHero() {
  return (
    <section className="relative min-h-[100svh] w-full overflow-hidden bg-canvas">
      {/* Drifting accent atmosphere — the palette, used boldly. */}
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div
          className="landing-drift-a absolute -bottom-1/4 -left-[12%] h-[70vh] w-[70vh] rounded-full"
          style={{
            background: "radial-gradient(circle, rgba(255,122,23,0.16), transparent 70%)",
            filter: "blur(38px)",
          }}
        />
        <div
          className="landing-drift-b absolute -right-[10%] -top-1/4 h-[62vh] w-[62vh] rounded-full"
          style={{
            background: "radial-gradient(circle, rgba(124,58,237,0.18), transparent 70%)",
            filter: "blur(38px)",
          }}
        />
      </div>

      <LandingNav />

      <div className="relative z-10 mx-auto grid min-h-[100svh] w-full max-w-7xl grid-cols-1 items-center gap-10 px-6 pb-16 pt-28 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:gap-8 lg:pb-0 lg:pt-0">
        {/* Left — the pitch. */}
        <div className="flex flex-col items-center text-center lg:items-start lg:text-left">
          <AlphaMark size={64} glow className="landing-rise" />

          <span
            className="landing-rise mt-6 font-mono text-[12px] uppercase tracking-[0.16em] text-body/70"
            style={{ animationDelay: "120ms" }}
          >
            Autonomous Research Platform
          </span>

          <h1
            className="landing-rise mt-5 text-balance text-[clamp(2.1rem,4.6vw,3.65rem)] font-normal leading-[1.04] tracking-[-0.03em] text-ink"
            style={{ animationDelay: "240ms" }}
          >
            Recursive sandboxed agents for{" "}
            <span className="bg-gradient-to-r from-[#ff7a17] via-[#ff9d5c] to-[#c4b5fd] bg-clip-text text-transparent">
              autonomous RL research
            </span>{" "}
            at scale
          </h1>

          <p
            className="landing-rise mt-6 max-w-md text-balance text-base leading-relaxed text-body/85 sm:text-lg"
            style={{ animationDelay: "440ms" }}
          >
            A lead agent scopes your goal, recursively spawns sandboxed sub-agents
            that run RL experiments in parallel, and streams the results back —
            live.
          </p>

          <div
            className="landing-rise mt-8 flex flex-col items-center gap-4 sm:flex-row"
            style={{ animationDelay: "600ms" }}
          >
            <LaunchGate />
            <span className="font-mono text-[12px] uppercase tracking-[0.1em] text-mute">
              Sandboxed cloud agents · results stream live
            </span>
          </div>
        </div>

        {/* Right — the live agent tree. */}
        <div className="relative h-[46vh] w-full lg:h-[82vh]">
          <AgentTreeField className="absolute inset-0" />
        </div>
      </div>
    </section>
  );
}

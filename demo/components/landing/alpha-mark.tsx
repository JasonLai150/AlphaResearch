import { cn } from "@/lib/utils";

/*
  The brand mark: the α glyph (the root agent) inscribed in a softly-rounded
  square (the sandbox) — glyph and sandbox in one. Type-as-logo, true to the
  DESIGN.md "unmarketed" posture. Reused as the nav logo, the hero focal point,
  and the source for app/icon.svg. `glow` lights it as the radiant hero root.
*/
export function AlphaMark({
  size = 32,
  glow = false,
  className,
}: {
  size?: number;
  glow?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center rounded-[28%] border border-hairline bg-canvas-card/60",
        glow && "border-sunset/40",
        className
      )}
      style={{ width: size, height: size }}
      aria-hidden
    >
      {glow && (
        <span
          className="pointer-events-none absolute inset-0 rounded-[28%]"
          style={{
            boxShadow:
              "0 0 24px 2px rgba(255,122,23,0.45), inset 0 0 18px rgba(255,122,23,0.18)",
          }}
        />
      )}
      <span
        className={cn(
          "relative font-sans leading-none text-ink",
          glow && "text-ink"
        )}
        style={{
          fontSize: size * 0.6,
          // The α sits optically low; nudge it onto the box's center line.
          transform: "translateY(-2%)",
          textShadow: glow ? "0 0 18px rgba(255,194,133,0.55)" : undefined,
        }}
      >
        α
      </span>
    </span>
  );
}

"use client";

import { Eyebrow } from "@/components/eyebrow";

/*
  Mocked outputs for one researcher — code-generated SVG artifacts (reward plot,
  sample rollout). More interactive visuals (animated gridworld) can slot in here
  via components/sim/*.
*/
export function OutputsGallery({
  artifacts,
}: {
  artifacts: { kind: string; url: string; caption: string }[];
}) {
  return (
    <div className="flex flex-col gap-2.5">
      <Eyebrow as="h3">Outputs</Eyebrow>
      {artifacts.length === 0 ? (
        <div className="rounded-xl border border-dashed border-hairline px-4 py-8 text-center text-[13px] text-mute">
          Plots and rollouts appear once the run completes.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {artifacts.map((a) => (
            <figure
              key={a.url.slice(0, 32) + a.kind}
              className="overflow-hidden rounded-xl border border-hairline bg-canvas-card"
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={a.url} alt={a.caption} className="block w-full" />
              <figcaption className="flex items-center justify-between px-3 py-2 text-[11px] text-mute">
                <span className="truncate">{a.caption}</span>
                <span className="ml-2 shrink-0 font-mono uppercase tracking-wider">
                  {a.kind}
                </span>
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}

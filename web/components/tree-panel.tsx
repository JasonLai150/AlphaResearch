import { AgentTree } from "@/components/agent-tree";
import { Eyebrow } from "@/components/eyebrow";
import { SubagentCard } from "@/components/subagent-card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { artifactUrl } from "@/lib/api";
import type { Subagent, TreeNode, WireArtifact } from "@/lib/types";

/** The right rail: the agent tree graph, subagents list, and artifacts. */
export function TreePanel({
  tree,
  subagents,
  artifacts,
}: {
  tree: TreeNode | null;
  subagents: Subagent[];
  artifacts: WireArtifact[];
}) {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-l border-hairline bg-canvas">
      <div className="flex items-center justify-between border-b border-hairline px-4 py-3">
        <Eyebrow as="h2">Tree</Eyebrow>
        <span className="text-[11px] text-mute">
          {subagents.length} subagent{subagents.length === 1 ? "" : "s"}
        </span>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-6 p-4">
          <div className="flex min-h-[120px] items-center justify-center rounded-lg border border-hairline bg-canvas-card/40 px-3 py-4">
            {tree ? (
              <AgentTree root={tree} />
            ) : (
              <span className="text-[12px] text-mute">No agents yet.</span>
            )}
          </div>

          <div className="flex flex-col gap-2.5">
            <Eyebrow as="h2">Subagents</Eyebrow>
            {subagents.length ? (
              <div className="flex flex-col gap-2">
                {subagents.map((a) => (
                  <SubagentCard key={a.id} agent={a} />
                ))}
              </div>
            ) : (
              <span className="text-[12px] text-mute">None dispatched yet.</span>
            )}
          </div>

          {artifacts.length > 0 && (
            <div className="flex flex-col gap-2.5">
              <Eyebrow as="h2">Artifacts</Eyebrow>
              <div className="flex flex-col gap-3">
                {artifacts.map((a) => (
                  <figure
                    key={a.id}
                    className="overflow-hidden rounded-lg border border-hairline bg-canvas-card"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={artifactUrl(a.url)}
                      alt={a.caption ?? a.kind}
                      className="block w-full"
                    />
                    {a.caption && (
                      <figcaption className="px-3 py-2 text-[11px] text-mute">
                        {a.caption}
                      </figcaption>
                    )}
                  </figure>
                ))}
              </div>
            </div>
          )}
        </div>
      </ScrollArea>
    </aside>
  );
}

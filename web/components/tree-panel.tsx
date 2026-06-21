import { AgentTree } from "@/components/agent-tree";
import { Eyebrow } from "@/components/eyebrow";
import { SubagentCard } from "@/components/subagent-card";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { Subagent, TreeNode } from "@/lib/types";

/** The right rail: the agent tree graph over the list of subagents. */
export function TreePanel({
  tree,
  subagents,
}: {
  tree: TreeNode;
  subagents: Subagent[];
}) {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col border-l border-hairline bg-canvas">
      <div className="flex items-center justify-between border-b border-hairline px-4 py-3">
        <Eyebrow as="h2">Tree</Eyebrow>
        <span className="text-[11px] text-mute">
          {subagents.length} subagents
        </span>
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-6 p-4">
          <div className="rounded-lg border border-hairline bg-canvas-card/40 px-3 py-4">
            <AgentTree root={tree} />
          </div>

          <div className="flex flex-col gap-2.5">
            <Eyebrow as="h2">Subagents</Eyebrow>
            <div className="flex flex-col gap-2">
              {subagents.map((a) => (
                <SubagentCard key={a.id} agent={a} />
              ))}
            </div>
          </div>
        </div>
      </ScrollArea>
    </aside>
  );
}

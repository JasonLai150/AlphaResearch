import type { AgentStatus, TreeNode } from "@/lib/types";
import { STATUS_HEX } from "@/lib/status-colors";

/*
  A compact tidy-tree layout for the agent graph. Leaves are spread evenly left
  to right; each parent is centered over its children. Rendered as inline SVG so
  it scales to the panel width via the viewBox. Node text inherits the page font
  (Geist) from the cascade. Colors are hardcoded brand hexes (SVG doesn't pick
  up Tailwind utility classes). Short labels keep the graph legible at panel
  width; full names + metrics live in the Subagents list below.
*/

const NODE_W = 48; // non-root box: single-char child or unlabeled status chip
const ROOT_W = 100; // root box, fits "Main agent"
const NODE_H = 32;
const H_GAP = 18;
const V_GAP = 52;
const FONT = 13;


interface Placed {
  id: string;
  label: string;
  status: AgentStatus;
  depth: number;
  x: number;
  y: number;
}

interface Edge {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

function layout(root: TreeNode) {
  const placed: Placed[] = [];
  const edges: Edge[] = [];
  const byId = new Map<string, Placed>();
  let leaf = 0;

  function walk(node: TreeNode, depth: number): number {
    const y = depth * V_GAP + NODE_H / 2;
    let x: number;
    if (!node.children?.length) {
      x = leaf * (NODE_W + H_GAP) + NODE_W / 2;
      leaf += 1;
    } else {
      const kids = node.children.map((c) => walk(c, depth + 1));
      x = (kids[0] + kids[kids.length - 1]) / 2;
    }
    const p: Placed = { id: node.id, label: node.label, status: node.status, depth, x, y };
    placed.push(p);
    byId.set(node.id, p);
    node.children?.forEach((c) => {
      const cp = byId.get(c.id);
      if (cp) edges.push({ x1: x, y1: y + NODE_H / 2, x2: cp.x, y2: cp.y - NODE_H / 2 });
    });
    return x;
  }

  walk(root, 0);
  const leaves = Math.max(leaf, 1);
  const width = leaves * (NODE_W + H_GAP) - H_GAP;
  const depthMax = placed.reduce((m, p) => Math.max(m, p.depth), 0);
  const height = depthMax * V_GAP + NODE_H;
  return { placed, edges, width, height };
}

export function AgentTree({ root }: { root: TreeNode }) {
  const { placed, edges, width, height } = layout(root);

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="mx-auto block h-auto w-full"
      role="img"
      aria-label="Agent tree showing the main agent and its subagents"
    >
      {edges.map((e, i) => (
        <path
          key={i}
          d={`M ${e.x1} ${e.y1} C ${e.x1} ${(e.y1 + e.y2) / 2}, ${e.x2} ${
            (e.y1 + e.y2) / 2
          }, ${e.x2} ${e.y2}`}
          fill="none"
          stroke="#2a2e35"
          strokeWidth={1}
        />
      ))}
      {placed.map((p) => {
        const isRoot = p.depth === 0;
        const w = isRoot ? ROOT_W : NODE_W;
        const hasLabel = p.label.length > 0;
        return (
          <g key={p.id} transform={`translate(${p.x - w / 2}, ${p.y - NODE_H / 2})`}>
            <rect
              width={w}
              height={NODE_H}
              rx={8}
              fill="#191919"
              stroke={isRoot ? "#3a3f47" : "#2f343c"}
              strokeWidth={1}
            />
            <circle
              cx={hasLabel ? 14 : w / 2}
              cy={NODE_H / 2}
              r={3}
              fill={STATUS_HEX[p.status]}
            />
            {hasLabel && (
              <text
                x={24}
                y={NODE_H / 2}
                dominantBaseline="central"
                fontSize={FONT}
                fill={isRoot ? "#ffffff" : "#dadbdf"}
              >
                {p.label}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

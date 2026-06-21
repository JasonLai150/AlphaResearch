import type { AgentStatus } from "@/lib/types";

/** Brand hexes for SVG/graph use (Tailwind classes don't apply to SVG fills). */
export const STATUS_HEX: Record<AgentStatus, string> = {
  running: "#ff7a17",
  done: "#ffffff",
  queued: "#7d8187",
  pending: "#7d8187",
  failed: "#ff7b72",
  cancelled: "#7d8187",
};

import type {
  ChatMessage,
  ChatSummary,
  CurrentUser,
  RepoContext,
  Subagent,
  TreeNode,
} from "@/lib/types";

/*
  Representative data so the Overview dashboard renders standalone, without a
  running backend. Shapes mirror lib/types.ts so the live SSE stream can be
  mapped onto these view models later. Copy is illustrative placeholder content.
*/

export const currentUser: CurrentUser = {
  name: "Aditya Billaume",
  handle: "adityabillaume",
  role: "Admin",
  initials: "A",
};

export const chats: ChatSummary[] = [
  { id: "c1", title: "PPO sample efficiency — DoorKey-8x8", updatedAt: "2m ago" },
  { id: "c2", title: "Reward shaping ablations", updatedAt: "1h ago" },
  { id: "c3", title: "Entropy coefficient sweep", updatedAt: "3h ago" },
  { id: "c4", title: "Curiosity-driven exploration (ICM)", updatedAt: "yesterday" },
  { id: "c5", title: "SAC vs PPO baseline", updatedAt: "2d ago" },
  { id: "c6", title: "Frame-stacking + LSTM policy", updatedAt: "4d ago" },
];

export const repoContext: RepoContext = {
  env: "Local",
  repo: "AlphaResearch",
  branch: "main",
  worktree: "wt/ppo-doorkey",
};

export const messages: ChatMessage[] = [
  {
    id: "m1",
    role: "user",
    author: "You",
    blocks: [
      "Improve PPO sample efficiency on MiniGrid-DoorKey-8x8. We're plateauing around 0.55 success after 2M steps. Spawn a few independent directions, run short pilots, and report rewards back — I'll pick the winners to scale.",
    ],
  },
  {
    id: "m2",
    role: "agent",
    author: "Lead agent",
    blocks: [
      "Read runner/configs/ppo_doorkey.yaml and the last three runs in Weights & Biases. The plateau lines up with the sparse reward — the policy rarely chains pick-up-key → open-door inside the episode budget, so the advantage estimates stay noisy.",
      "Branching three independent directions, each isolated in its own worktree so they don't share state:",
      "• X — Curiosity (ICM): add an intrinsic exploration bonus for novel states.",
      "• Y — Subgoal shaping: dense reward for key pickup and reaching the door.",
      "• Z — GAE-λ + batch-size sweep: stabilize the advantage estimates.",
    ],
    activity: {
      label: "Ran 4 tools · read config, queried W&B, opened 3 worktrees",
      status: "running",
    },
  },
  {
    id: "m3",
    role: "agent",
    author: "Lead agent",
    blocks: [
      "First signal from the 50k-step pilots (8 seeds each):",
      "• X (ICM) is already at 0.81 success — curiosity is cracking the key→door chaining.",
      "• Y (subgoal shaping) sits at 0.64 and is still climbing.",
      "• Z (GAE sweep) is queued behind a free runner.",
    ],
    activity: {
      label: "3 subagents dispatched · 17 evals running",
      status: "running",
    },
  },
  {
    id: "m4",
    role: "user",
    author: "You",
    blocks: [
      "X looks strong. Before we scale it — can you confirm it's actually completing levels, not just farming the curiosity bonus?",
    ],
  },
  {
    id: "m5",
    role: "agent",
    author: "Lead agent",
    blocks: [
      "Checked. Logging extrinsic-only success separately, X holds at 0.79 on pure task reward (curiosity excluded), so it's genuinely solving DoorKey rather than chasing novelty. The remaining failures are long detours, not skipped keys.",
      "Recommendation: promote X to the full 2M-step run and fold Y's subgoal shaping in as an ablation. Z can wait for a runner.",
    ],
    activity: {
      label: "Ran 2 tools · pulled eval videos, recomputed task reward",
      status: "done",
    },
  },
];

// Short node labels keep the graph legible inside the narrow panel; full names
// and metrics live in the Subagents list below it.
export const agentTree: TreeNode = {
  id: "root",
  label: "Main agent",
  status: "running",
  children: [
    { id: "x", label: "X", status: "running" },
    {
      id: "y",
      label: "Y",
      status: "running",
      // Y's two parallel eval runs — rendered as compact status chips.
      children: [
        { id: "y1", label: "", status: "done" },
        { id: "y2", label: "", status: "running" },
      ],
    },
    { id: "z", label: "Z", status: "queued" },
  ],
};

export const subagents: Subagent[] = [
  {
    id: "x",
    name: "X",
    kind: "Curiosity (ICM)",
    status: "running",
    reward: 0.812,
  },
  {
    id: "y",
    name: "Y",
    kind: "Subgoal shaping",
    status: "running",
    reward: 0.643,
  },
  {
    id: "z",
    name: "Z",
    kind: "GAE-λ sweep",
    status: "queued",
    note: "queued · waiting for a free runner",
  },
];

import Anthropic from "@anthropic-ai/sdk";

/*
  Server-only thin wrapper around the Anthropic SDK. The demo uses it to generate
  the LEAD agent's chat prose (plan / progress / final / follow-up replies) and
  the per-researcher summaries — grounded on the deterministic scenario so the
  numbers (curves, rewards, winner) stay reproducible while the words come from a
  real model. Imported only by server-side route handlers / the live producer;
  the API key (process.env.ANTHROPIC_API_KEY) never reaches the browser.

  When no key is set, claudeEnabled() is false and callers fall back to the
  templated narrative — so the offline mock + the test suite are unaffected.
*/

const MODEL = process.env.DEMO_CLAUDE_MODEL || "claude-opus-4-8";

let client: Anthropic | null = null;

export function claudeEnabled(): boolean {
  return Boolean(process.env.ANTHROPIC_API_KEY);
}

function getClient(): Anthropic {
  // Lazily construct so importing this module is free when the key is absent.
  if (!client) client = new Anthropic();
  return client;
}

export interface ProseRequest {
  system: string;
  prompt: string;
  /** Hard ceiling on output length. Demo prose is short, so keep it tight. */
  maxTokens?: number;
}

/**
 * Stream a single assistant turn from Claude. Invokes `onDelta` with each text
 * chunk as it arrives (so the caller can pump SSE tokens live), and resolves
 * with the full text. Thinking is disabled for snappy, low-latency prose; a
 * final-answer-only system instruction keeps reasoning out of the output.
 */
export async function streamProse(
  { system, prompt, maxTokens = 600 }: ProseRequest,
  onDelta?: (delta: string) => void
): Promise<string> {
  const stream = getClient().messages.stream({
    model: MODEL,
    max_tokens: maxTokens,
    thinking: { type: "disabled" },
    system,
    messages: [{ role: "user", content: prompt }],
  });
  let full = "";
  stream.on("text", (delta) => {
    full += delta;
    onDelta?.(delta);
  });
  await stream.finalMessage();
  return full.trim();
}

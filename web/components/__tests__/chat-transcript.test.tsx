import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChatTranscript } from "@/components/chat-transcript";
import type { TranscriptItem } from "@/lib/types";

function item(over: Partial<TranscriptItem>): TranscriptItem {
  return { id: "t0", role: "assistant", text: "hello", ...over };
}

describe("ChatTranscript typewriter caret", () => {
  it("shows a caret on a streaming assistant item", () => {
    render(<ChatTranscript items={[item({ streaming: true })]} />);
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByTestId("stream-caret")).toBeInTheDocument();
  });

  it("shows no caret once streaming has finished", () => {
    render(<ChatTranscript items={[item({ streaming: false })]} />);
    expect(screen.queryByTestId("stream-caret")).toBeNull();
  });

  it("shows no caret on a user message", () => {
    render(<ChatTranscript items={[item({ role: "user", streaming: true })]} />);
    expect(screen.queryByTestId("stream-caret")).toBeNull();
  });
});

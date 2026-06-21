"use client";

import { useState } from "react";
import { ArrowUp } from "lucide-react";

import { Button } from "@/components/ui/button";

/** The message composer pinned to the bottom of the transcript column. */
export function ChatComposer() {
  const [value, setValue] = useState("");
  const canSend = value.trim().length > 0;

  return (
    <div className="border-t border-hairline px-4 py-3 md:px-6">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (canSend) setValue("");
        }}
        className="mx-auto flex max-w-3xl items-end gap-2 rounded-lg border border-hairline bg-canvas-soft px-3 py-2 transition-colors focus-within:ring-2 focus-within:ring-ring"
      >
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (canSend) setValue("");
            }
          }}
          rows={1}
          placeholder="Message the lead agent…"
          aria-label="Message the lead agent"
          className="max-h-40 flex-1 resize-none bg-transparent py-1.5 text-sm text-ink placeholder:text-mute focus:outline-none"
        />
        <Button
          type="submit"
          size="icon"
          className="size-8 shrink-0"
          disabled={!canSend}
          aria-label="Send message"
        >
          <ArrowUp className="size-4" />
        </Button>
      </form>
      <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-mute">
        Enter to send · Shift+Enter for a new line
      </p>
    </div>
  );
}

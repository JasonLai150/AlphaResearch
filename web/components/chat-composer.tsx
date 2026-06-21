"use client";

import { useRef, useState } from "react";
import { ArrowUp, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";

/** Message composer — submits a goal (new session) or a follow-up turn. */
export function ChatComposer({
  onSubmit,
  placeholder = "Message the lead agent…",
  busy = false,
  hint = "Enter to send · Shift+Enter for a new line",
}: {
  onSubmit: (text: string) => void | Promise<void>;
  placeholder?: string;
  busy?: boolean;
  hint?: string;
}) {
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // The composer is busy when the caller says so or while a submit is in flight.
  const isBusy = busy || sending;
  const canSend = value.trim().length > 0 && !isBusy;

  async function submit() {
    const text = value.trim();
    if (!text || isBusy) return;

    // Clear optimistically so the field feels instant.
    setValue("");
    setSending(true);
    try {
      await onSubmit(text);
    } catch {
      // Restore the text on failure and return focus so the user can retry.
      setValue(text);
      requestAnimationFrame(() => textareaRef.current?.focus());
    } finally {
      // Always re-enable — the textarea must never be stuck disabled after a reject.
      setSending(false);
    }
  }

  return (
    <div className="border-t border-hairline px-4 py-3 md:px-6">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="mx-auto flex max-w-3xl items-end gap-2 rounded-lg border border-hairline bg-canvas-soft px-3 py-2 transition-colors focus-within:ring-2 focus-within:ring-ring"
      >
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={1}
          placeholder={placeholder}
          aria-label={placeholder}
          disabled={isBusy}
          className="max-h-40 flex-1 resize-none bg-transparent py-1.5 text-sm text-ink placeholder:text-mute focus:outline-none disabled:opacity-60"
        />
        <Button
          type="submit"
          size="icon"
          className="size-8 shrink-0"
          disabled={!canSend}
          aria-label="Send message"
        >
          {isBusy ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <ArrowUp className="size-4" />
          )}
        </Button>
      </form>
      <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-mute">
        {hint}
      </p>
    </div>
  );
}

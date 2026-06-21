"use client";

import { useRef, useState } from "react";
import { ArrowUp, Loader2, Repeat } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { AutonomousOptions } from "@/hooks/use-chat-submit";

/** Message composer — submits a goal (new session) or a follow-up turn. */
export function ChatComposer({
  onSubmit,
  placeholder = "Message the lead agent…",
  busy = false,
  hint = "Enter to send · Shift+Enter for a new line",
  allowAutonomous = false,
}: {
  onSubmit: (text: string, opts?: AutonomousOptions) => void | Promise<void>;
  placeholder?: string;
  busy?: boolean;
  hint?: string;
  /** Show the autonomous-loop toggle + controls (new-session composer only). */
  allowAutonomous?: boolean;
}) {
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);
  const [autonomous, setAutonomous] = useState(false);
  const [maxRounds, setMaxRounds] = useState("5");
  const [goalMetric, setGoalMetric] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // The composer is busy when the caller says so or while a submit is in flight.
  const isBusy = busy || sending;
  const canSend = value.trim().length > 0 && !isBusy;

  function autonomousOpts(): AutonomousOptions | undefined {
    if (!allowAutonomous || !autonomous) return undefined;
    const rounds = parseInt(maxRounds, 10);
    const goal = parseFloat(goalMetric);
    return {
      mode: "autonomous",
      maxRounds: Number.isFinite(rounds) && rounds > 0 ? rounds : undefined,
      goalMetric: Number.isFinite(goal) ? goal : undefined,
    };
  }

  async function submit() {
    const text = value.trim();
    if (!text || isBusy) return;

    const opts = autonomousOpts();
    // Clear optimistically so the field feels instant.
    setValue("");
    setSending(true);
    try {
      await onSubmit(text, opts);
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
      {allowAutonomous && (
        <div className="mx-auto mb-2 flex max-w-3xl flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => setAutonomous((a) => !a)}
            aria-pressed={autonomous}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1",
              "font-mono text-[11px] uppercase tracking-wider transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              autonomous
                ? "border-sunset/40 bg-sunset/10 text-sunset"
                : "border-hairline bg-canvas-soft text-mute hover:text-ink"
            )}
          >
            <Repeat className="size-3" aria-hidden />
            Autonomous loop
          </button>
          {autonomous && (
            <div className="flex flex-wrap items-center gap-3 text-[12px] text-mute">
              <label className="flex items-center gap-1.5">
                Max rounds
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={maxRounds}
                  onChange={(e) => setMaxRounds(e.target.value)}
                  className="w-14 rounded-md border border-hairline bg-canvas-soft px-2 py-0.5 text-ink focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </label>
              <label className="flex items-center gap-1.5">
                Target metric
                <input
                  type="number"
                  step="0.01"
                  placeholder="optional"
                  value={goalMetric}
                  onChange={(e) => setGoalMetric(e.target.value)}
                  className="w-20 rounded-md border border-hairline bg-canvas-soft px-2 py-0.5 text-ink placeholder:text-mute focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </label>
            </div>
          )}
        </div>
      )}
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

"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

/*
  Demo launch gate. The hero's primary CTA opens a small password modal instead
  of linking straight to the console. This is a "for now" demo affordance — the
  password lives in the bundle (it is not a secret) and `/app` itself stays
  open, so this gates the launch button, not the route. Single source of truth
  for the password below.
*/
export const DEMO_PASSWORD = "1234";

export function LaunchGate() {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function close() {
    setOpen(false);
    setValue("");
    setError(false);
  }

  // Focus the field as the modal opens.
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Dismiss on Escape while open.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (value === DEMO_PASSWORD) {
      // Full-page navigation — keeps the gate free of Next router context.
      window.location.assign("/app");
      return;
    }
    setError(true);
  }

  return (
    <>
      <Button size="lg" className="px-7" onClick={() => setOpen(true)}>
        Launch app
      </Button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-canvas/80 p-6 backdrop-blur-sm"
          onClick={close}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="launch-gate-title"
            className="w-full max-w-sm rounded-2xl border border-hairline bg-canvas-card p-6 text-left shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h2
              id="launch-gate-title"
              className="text-lg font-normal tracking-[-0.01em] text-ink"
            >
              Enter demo password
            </h2>
            <p className="mt-1 text-sm text-mute">
              This preview is gated. Enter the demo password to launch the
              console.
            </p>

            <form onSubmit={submit} className="mt-5 flex flex-col gap-2">
              <label
                htmlFor="launch-gate-password"
                className="text-xs uppercase tracking-[0.12em] text-mute"
              >
                Demo password
              </label>
              <Input
                id="launch-gate-password"
                ref={inputRef}
                type="password"
                autoComplete="off"
                value={value}
                onChange={(e) => {
                  setValue(e.target.value);
                  if (error) setError(false);
                }}
                aria-invalid={error || undefined}
                aria-describedby={error ? "launch-gate-error" : undefined}
              />
              {error && (
                <p id="launch-gate-error" className="text-sm text-destructive">
                  Incorrect password. Try again.
                </p>
              )}
              <div className="mt-1 flex justify-end gap-2">
                <Button type="button" variant="outline" onClick={close}>
                  Cancel
                </Button>
                <Button type="submit">Enter</Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

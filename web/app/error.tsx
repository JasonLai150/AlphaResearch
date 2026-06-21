"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/eyebrow";

/*
  Route-segment error boundary. Next.js renders this in place of the page tree
  when a render/data error escapes a Client/Server Component below it. The app
  shell (layout) stays mounted, so we lean on the normal design tokens.
*/
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("route error boundary", error);
  }, [error]);

  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-6 bg-canvas px-6 text-center text-ink">
      <div className="flex flex-col items-center gap-3">
        <AlertTriangle className="size-7 text-sunset" aria-hidden />
        <Eyebrow>Something went wrong</Eyebrow>
        <h1 className="max-w-xl text-2xl tracking-[-0.02em] text-ink">
          The console hit an unexpected error
        </h1>
        <p className="max-w-md text-sm text-mute">
          {error.message || "An unknown error occurred while rendering this view."}
        </p>
        {error.digest ? (
          <p className="font-mono text-[12px] tracking-[0.04em] text-mute/70">
            digest {error.digest}
          </p>
        ) : null}
      </div>
      <Button variant="outline" onClick={() => reset()}>
        Try again
      </Button>
    </div>
  );
}

"use client";

import { useEffect } from "react";

/*
  Root-level error boundary. This replaces the entire document — including the
  root layout's <html>/<body> — when an error is thrown in the layout itself,
  so it must render its own <html>/<body> and cannot rely on the app shell or
  shared components. Styling is inlined with the brand tokens (dark canvas,
  white ink, sunset accent) so it survives even when globals.css is unavailable.
*/
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("global error boundary", error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          padding: "1.5rem",
          textAlign: "center",
          backgroundColor: "#0a0a0a",
          color: "#ffffff",
          fontFamily:
            'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
          WebkitFontSmoothing: "antialiased",
        }}
      >
        <h1
          style={{
            margin: 0,
            fontSize: "1.5rem",
            fontWeight: 400,
            letterSpacing: "-0.02em",
          }}
        >
          The console crashed
        </h1>
        <p
          style={{
            margin: 0,
            maxWidth: "28rem",
            fontSize: "0.875rem",
            color: "#7d8187",
          }}
        >
          {error.message || "An unknown error occurred."}
        </p>
        <button
          type="button"
          onClick={() => reset()}
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            height: "2.25rem",
            padding: "0 1rem",
            borderRadius: "9999px",
            border: "1px solid #212327",
            backgroundColor: "transparent",
            color: "#ffffff",
            fontSize: "0.875rem",
            fontWeight: 400,
            cursor: "pointer",
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}

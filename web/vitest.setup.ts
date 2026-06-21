import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// vitest runs with globals:false, so Testing Library's auto-cleanup afterEach
// isn't auto-registered. Without this, rendered DOM leaks between tests in a file.
afterEach(() => cleanup());

// jsdom doesn't implement scrollIntoView; components that auto-scroll (e.g.
// chat-transcript pinning to the latest message) call it on mount.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

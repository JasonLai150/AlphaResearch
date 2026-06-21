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

// vitest's jsdom environment (jsdom 29 under Node 22) does not expose a Web
// Storage `localStorage` — Node logs "localStorage is not available because
// --localstorage-file was not provided" and the global stays undefined. Provide
// a minimal in-memory Storage shim so components that persist UI state (e.g. the
// resizable sidebar width) work under test. Guarded, so a real implementation
// (browsers, a future vitest with native storage) is never overridden.
if (typeof globalThis.localStorage === "undefined") {
  const store = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    removeItem: (key: string) => void store.delete(key),
    setItem: (key: string, value: string) => void store.set(key, String(value)),
  };
  Object.defineProperty(globalThis, "localStorage", {
    value: storage,
    configurable: true,
  });
}

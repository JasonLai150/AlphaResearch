import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

// vitest runs with globals:false, so Testing Library's auto-cleanup afterEach
// isn't auto-registered. Without this, rendered DOM leaks between tests in a file.
afterEach(() => cleanup());

// Components that navigate (AppSidebar, AppShell) call next/navigation hooks,
// which need the App Router context that jsdom lacks. Provide a safe default
// (pathname "/", no-op router) globally; individual tests can override this
// file-local mock with their own vi.mock("next/navigation", …) when they need
// to drive a specific path.
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({
    push: () => {},
    replace: () => {},
    back: () => {},
    forward: () => {},
    refresh: () => {},
    prefetch: () => {},
  }),
  useSearchParams: () => new URLSearchParams(),
}));

// jsdom doesn't implement scrollIntoView; components that auto-scroll (e.g.
// chat-transcript pinning to the latest message) call it on mount.
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}

// This jsdom setup ships without Web Storage. Provide a minimal in-memory
// localStorage so storage-backed modules (settings-store) run under test the
// way they do in a real browser. (globalThis === window in jsdom, so this also
// satisfies window.localStorage.) Define it unconditionally rather than reading
// globalThis.localStorage first — reading Node's experimental getter emits a
// warning, and there's never a real Web Storage to preserve under jsdom.
{
  const store = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return store.size;
    },
    clear: () => store.clear(),
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    key: (i: number) => [...store.keys()][i] ?? null,
    removeItem: (k: string) => {
      store.delete(k);
    },
    setItem: (k: string, v: string) => {
      store.set(k, String(v));
    },
  };
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: storage,
  });
}

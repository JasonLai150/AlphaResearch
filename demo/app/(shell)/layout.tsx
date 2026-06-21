import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";

// Route group: the parentheses keep these pages off the URL while sharing one
// layout. Every page under (shell) renders inside the persistent sidebar shell.
export default function ShellLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}

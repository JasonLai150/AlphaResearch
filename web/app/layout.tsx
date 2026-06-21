import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { ClerkProvider } from "@clerk/nextjs";

import { AppAuthProvider } from "@/components/auth/app-auth";
import { CLERK_ENABLED } from "@/lib/auth-config";

export const metadata: Metadata = {
  title: "Alpha Research — Overview",
  description: "Recursive automated RL research console",
};

// Dark-canvas theming for Clerk's hosted components.
const clerkAppearance = {
  variables: {
    colorBackground: "#0a0a0a",
    colorInputBackground: "#1a1c20",
    colorText: "#ffffff",
    colorTextSecondary: "#7d8187",
    colorInputText: "#ffffff",
    colorPrimary: "#ffffff",
    borderRadius: "0.5rem",
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const tree = (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>
        <AppAuthProvider>{children}</AppAuthProvider>
      </body>
    </html>
  );

  return CLERK_ENABLED ? (
    <ClerkProvider appearance={clerkAppearance}>{tree}</ClerkProvider>
  ) : (
    tree
  );
}

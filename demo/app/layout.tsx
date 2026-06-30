import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";

import { AppAuthProvider } from "@/components/auth/app-auth";
import { Toaster } from "@/components/ui/sonner";

export const metadata: Metadata = {
  title: "Alpha Research — Console",
  description: "Recursive automated RL research console — interactive demo",
};

// DEMO build: no ClerkProvider — the app always renders as a fixed demo user.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>
        <AppAuthProvider>{children}</AppAuthProvider>
        <Toaster />
      </body>
    </html>
  );
}

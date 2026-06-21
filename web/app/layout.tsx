import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { ClerkProvider } from "@clerk/nextjs";

import { AppAuthProvider } from "@/components/auth/app-auth";
import { Toaster } from "@/components/ui/sonner";
import { CLERK_ENABLED } from "@/lib/auth-config";

export const metadata: Metadata = {
  title: "Alpha Research — Overview",
  description: "Recursive automated RL research console",
  icons: { icon: "/image.png" },
};

// Dark-canvas theming for Clerk's hosted components. Variables set the palette;
// `elements` push the primary CTA and inputs into the design-system pill shape
// (rounded-full white-filled CTA, hairline-bordered card on the canvas).
const clerkAppearance = {
  variables: {
    colorBackground: "#0a0a0a",
    colorInputBackground: "#1a1c20",
    colorText: "#ffffff",
    colorTextSecondary: "#7d8187",
    colorInputText: "#ffffff",
    colorPrimary: "#ffffff",
    colorNeutral: "#ffffff",
    borderRadius: "9999px",
  },
  elements: {
    rootBox: "w-full",
    cardBox:
      "border border-[#212327] bg-[#191919] shadow-none rounded-2xl",
    card: "bg-transparent shadow-none",
    headerTitle: "text-[#ffffff]",
    headerSubtitle: "text-[#7d8187]",
    socialButtonsBlockButton:
      "rounded-full border border-[#212327] bg-transparent text-[#ffffff] hover:bg-[#1a1c20]",
    formFieldInput:
      "rounded-full border border-[#212327] bg-[#1a1c20] text-[#ffffff]",
    formButtonPrimary:
      "rounded-full bg-[#ffffff] text-[#0a0a0a] font-normal normal-case shadow-none hover:bg-[#fafaf7]",
    footerActionLink: "text-[#ffffff] hover:text-[#fafaf7]",
    footer: "bg-transparent",
    dividerLine: "bg-[#212327]",
    dividerText: "text-[#7d8187]",
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  const tree = (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>
        <AppAuthProvider>{children}</AppAuthProvider>
        <Toaster />
      </body>
    </html>
  );

  return CLERK_ENABLED ? (
    <ClerkProvider appearance={clerkAppearance} afterSignOutUrl="/">
      {tree}
    </ClerkProvider>
  ) : (
    tree
  );
}

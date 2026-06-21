import "./globals.css";
import type { ReactNode } from "react";

export const metadata = {
  title: "AlphaResearch",
  description: "Recursive automated RL research",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

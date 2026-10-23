import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Shell } from "@/components/shell";

import "./globals.css";

export const metadata: Metadata = {
  title: "TenderBridge",
  description: "Evidence-first bid / no-bid copilot for IT-infrastructure tenders",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}

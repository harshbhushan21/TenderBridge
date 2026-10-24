import type { Metadata } from "next";
import { Montserrat, Poppins } from "next/font/google";
import type { ReactNode } from "react";

import { Shell } from "@/components/shell";

import "./globals.css";

// Self-hosted by next/font at build time: no request to Google when the page loads.
const montserrat = Montserrat({ subsets: ["latin"], variable: "--font-montserrat", display: "swap" });
const poppins = Poppins({ subsets: ["latin"], weight: ["500", "600", "700"], variable: "--font-poppins",
  display: "swap" });

export const metadata: Metadata = {
  title: "TenderBridge",
  description: "Evidence-first bid / no-bid copilot for IT-infrastructure tenders",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${montserrat.variable} ${poppins.variable}`}>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}

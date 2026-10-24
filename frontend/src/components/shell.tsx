"use client";

import { Activity, FileSearch, Library, LayoutDashboard, PlusCircle, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useRole } from "@/hooks/use-role";
import { DEMO_IDENTITIES, setRole, type DemoRole } from "@/lib/api";
import { cn } from "@/lib/formatting";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/tenders/new", label: "New tender", icon: PlusCircle },
  { href: "/kb", label: "Knowledge base", icon: Library },
  { href: "/ops", label: "AgentOps", icon: Activity },
];

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const role = useRole();
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-56 shrink-0 border-r border-slate-200 bg-white md:block">
        <Link href="/" className="flex items-center gap-2 px-4 py-4 text-base font-semibold text-slate-900">
          <FileSearch className="size-5" /> TenderBridge
        </Link>
        <nav className="space-y-1 px-2">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link key={href} href={href}
                className={cn("flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium",
                  active ? "bg-slate-100 text-slate-900" : "text-slate-600 hover:bg-slate-50")}>
                <Icon className="size-4" /> {label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-2">
          <p className="text-xs text-slate-500">
            Demo data is synthetic: a simulated tender and a fictional bidder. Nothing is submitted to any portal.
          </p>
          <label className="flex items-center gap-2 text-sm">
            <ShieldCheck className="size-4 text-slate-500" />
            <span className="text-slate-500">Acting as</span>
            <select aria-label="Demo role" value={role} onChange={(e) => setRole(e.target.value as DemoRole)}
              className="rounded-md border border-slate-300 bg-white px-2 py-1 text-sm">
              {(Object.keys(DEMO_IDENTITIES) as DemoRole[]).map((r) => (
                <option key={r} value={r}>{DEMO_IDENTITIES[r].label}</option>
              ))}
            </select>
          </label>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}

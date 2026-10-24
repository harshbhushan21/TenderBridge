"use client";

import { Activity, FileSearch, LayoutDashboard, Library, PlusCircle } from "lucide-react";
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
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col bg-slate-900 text-slate-300 md:flex">
        <Link href="/" className="flex items-center gap-3 px-5 py-6">
          <span className="grid size-9 place-items-center rounded-md bg-slate-200 text-slate-900">
            <FileSearch className="size-5" />
          </span>
          <span className="font-display text-[17px] font-semibold text-slate-50">TenderBridge</span>
        </Link>
        <nav className="space-y-1 px-3">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link key={href} href={href}
                className={cn("flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                  active ? "bg-slate-700 text-slate-50" : "text-slate-300 hover:bg-slate-800 hover:text-slate-50")}>
                <Icon className={cn("size-4", active ? "text-slate-300" : "text-slate-400")} /> {label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 py-2.5 md:justify-end md:px-8">
          <span className="font-display font-semibold text-slate-900 md:hidden">TenderBridge</span>
          <label className="flex items-center gap-2 text-sm">
                        <span className="text-slate-500">Acting as</span>
            <select aria-label="Demo role" value={role} onChange={(e) => setRole(e.target.value as DemoRole)}
              className="border border-slate-300 bg-white px-2.5 py-1.5 text-sm font-medium text-slate-800">
              {(Object.keys(DEMO_IDENTITIES) as DemoRole[]).map((r) => (
                <option key={r} value={r}>{DEMO_IDENTITIES[r].label}</option>
              ))}
            </select>
          </label>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </div>
  );
}

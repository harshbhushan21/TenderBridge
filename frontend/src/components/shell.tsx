"use client";

import { Activity, ChevronDown, FileSearch, LayoutDashboard, Library, PlusCircle } from "lucide-react";
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

function section(pathname: string): string {
  if (pathname === "/tenders/new") return "New tender";
  if (pathname.startsWith("/tenders")) return "Tender workspace";
  return NAV.find((n) => n.href !== "/" && pathname.startsWith(n.href))?.label ?? "Dashboard";
}

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const role = useRole();
  const identity = DEMO_IDENTITIES[role];
  const initials = identity.label.split(" ").map((w) => w[0]).join("");
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col bg-ink text-slate-300 md:flex">
        <Link href="/" className="flex h-16 items-center gap-3 border-b border-white/10 px-5">
          <span className="grid size-8 place-items-center rounded-md bg-olive text-white">
            <FileSearch className="size-[18px]" />
          </span>
          <span className="font-display text-[17px] font-semibold text-white">TenderBridge</span>
        </Link>
        <div className="px-5 pb-2 pt-6 text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-400">Workspace</div>
        <nav className="space-y-0.5 px-3">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link key={href} href={href}
                className={cn("relative flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  active ? "bg-olive/45 text-white" : "text-slate-300 hover:bg-white/5 hover:text-white")}>
                {active && <span className="absolute inset-y-1.5 left-0 w-[3px] rounded-full bg-olive" />}
                <Icon className={cn("size-4", active ? "text-white" : "text-slate-400")} /> {label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between gap-3 border-b border-slate-200 bg-white px-4 md:px-8">
          <span className="font-display text-[15px] font-semibold text-slate-900">
            <span className="md:hidden">TenderBridge · </span>{section(pathname)}
          </span>
          <label className="relative flex cursor-pointer items-center gap-2.5 rounded-lg border border-slate-200 py-1 pl-1 pr-2 hover:border-slate-300">
            <span className="grid size-7 place-items-center rounded-md bg-olive text-[11px] font-semibold text-white">{initials}</span>
            <span className="hidden text-left leading-tight sm:block">
              <span className="block text-xs font-semibold text-slate-900">{identity.label}</span>
              <span className="block text-[11px] text-slate-500">{identity.user}</span>
            </span>
            <select aria-label="Switch role" value={role} onChange={(e) => setRole(e.target.value as DemoRole)}
                className="absolute inset-0 cursor-pointer opacity-0">
                {(Object.keys(DEMO_IDENTITIES) as DemoRole[]).map((r) => (
                  <option key={r} value={r}>{DEMO_IDENTITIES[r].label}</option>
                ))}
              </select>
            <ChevronDown className="size-4 text-slate-400" />
          </label>
        </header>
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </div>
  );
}

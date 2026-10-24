"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn, humanize, statusTone, toneClasses, type Tone } from "@/lib/formatting";

export function Badge({ status, tone, children, className }: {
  status?: string | null; tone?: Tone; children?: ReactNode; className?: string;
}) {
  const t = tone ?? statusTone(status);
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
      toneClasses[t], className)}>
      {children ?? humanize(status)}
    </span>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  loading?: boolean;
};

export function Button({ variant = "primary", loading, disabled, className, children, ...rest }: ButtonProps) {
  const styles = {
    primary: "bg-slate-900 text-slate-50 shadow-sm hover:bg-slate-700 disabled:bg-slate-400",
    secondary: "bg-white text-slate-800 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 hover:ring-slate-400 disabled:text-slate-400",
    danger: "bg-red-600 text-white shadow-sm hover:bg-red-500 disabled:bg-red-200",
    ghost: "text-slate-700 hover:bg-slate-100 disabled:text-slate-400",
  }[variant];
  return (
    <button {...rest} disabled={disabled || loading}
      className={cn("inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-semibold",
        "transition-colors disabled:cursor-not-allowed", styles, className)}>
      {loading && <Loader2 className="size-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Card({ title, actions, children, className }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={cn("rounded-xl border border-slate-200 bg-white shadow-card", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
          <h2 className="text-[15px] font-semibold">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500">
      <Loader2 className="size-4 animate-spin" /> {label ?? "Loading…"}
    </div>
  );
}

export function ErrorBanner({ error }: { error: string | null | undefined }) {
  if (!error) return null;
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      <AlertTriangle className="mt-0.5 size-4 shrink-0" /> <span>{error}</span>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed border-slate-300 bg-white/60 p-8 text-center text-sm text-slate-500">{children}</p>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: ReactNode }[]; value: T; onChange: (id: T) => void;
}) {
  return (
    <nav className="flex gap-1 overflow-x-auto border-b border-slate-200" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cn("-mb-px whitespace-nowrap border-b-2 px-3.5 py-2.5 text-sm font-medium transition-colors",
            value === t.id ? "border-slate-900 font-semibold text-slate-900"
              : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800")}>
          {t.label}
        </button>
      ))}
    </nav>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">{label}</div>
      <div className="mt-1 font-display text-xl font-semibold text-slate-900">{value}</div>
      {hint && <div className="text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

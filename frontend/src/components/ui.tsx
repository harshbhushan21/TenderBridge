"use client";

import { AlertTriangle, CheckCircle2, Clock, Info, Loader2, XCircle, type LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn, humanize, solidToneClasses, statusTone, toneClasses, type Tone } from "@/lib/formatting";

const TONE_ICONS: Partial<Record<Tone, LucideIcon>> = {
  green: CheckCircle2, amber: AlertTriangle, red: XCircle, violet: Clock,
};

export function Badge({ status, tone, solid, children, className }: {
  status?: string | null; tone?: Tone; solid?: boolean; children?: ReactNode; className?: string;
}) {
  const t = tone ?? statusTone(status);
  const Icon = TONE_ICONS[t];
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium",
      solid ? cn("rounded-md px-2.5 py-1 font-semibold tracking-wide", solidToneClasses[t]) : toneClasses[t], className)}>
      {Icon && <Icon className="size-3.5 shrink-0" strokeWidth={2.25} />}
      {children ?? humanize(status)}
    </span>
  );
}

const CALLOUT = {
  red: { icon: XCircle, box: "border-red-600 bg-red-50 text-red-800", icon_: "text-red-600" },
  amber: { icon: AlertTriangle, box: "border-amber-600 bg-amber-50 text-amber-900", icon_: "text-amber-600" },
  blue: { icon: Info, box: "border-sky-600 bg-sky-50 text-sky-800", icon_: "text-sky-600" },
} as const;

/** Inline alert: tinted panel, accent edge and an icon, so warnings read at a glance. */
export function Callout({ tone = "amber", children, className, role }: {
  tone?: keyof typeof CALLOUT; children: ReactNode; className?: string; role?: string;
}) {
  const c = CALLOUT[tone];
  return (
    <div role={role} className={cn("flex items-start gap-2.5 rounded-md border-l-[3px] px-3 py-2.5 text-sm", c.box, className)}>
      <c.icon className={cn("mt-0.5 size-4 shrink-0", c.icon_)} strokeWidth={2.25} />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "success" | "secondary" | "danger" | "ghost";
  loading?: boolean;
};

export function Button({ variant = "primary", loading, disabled, className, children, ...rest }: ButtonProps) {
  const styles = {
    primary: "bg-ink text-white shadow-sm hover:bg-slate-700 disabled:bg-slate-400 disabled:shadow-none",
    success: "bg-ok text-white shadow-sm hover:bg-emerald-800 disabled:bg-slate-400 disabled:shadow-none",
    secondary: "bg-white text-slate-800 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 hover:ring-slate-400 disabled:text-slate-400",
    danger: "bg-danger text-white shadow-sm hover:bg-red-800 disabled:bg-red-200 disabled:shadow-none",
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
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-3.5">
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
  return <Callout tone="red" role="alert">{error}</Callout>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">{children}</p>;
}

export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: { id: T; label: ReactNode }[]; value: T; onChange: (id: T) => void;
}) {
  return (
    <nav className="flex gap-1 overflow-x-auto border-b border-slate-200" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cn("-mb-px whitespace-nowrap border-b-2 px-3.5 py-2.5 text-sm font-medium transition-colors",
            value === t.id ? "border-olive font-semibold text-slate-900"
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

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { SourceSpan } from "./types";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatInrCrore(inr: number | null | undefined, digits = 2): string {
  if (inr === null || inr === undefined || Number.isNaN(inr)) return "—";
  const cr = inr / 1e7;
  return `₹${cr.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: 0 })} Cr`;
}

export function formatInr(inr: number | null | undefined): string {
  if (inr === null || inr === undefined || Number.isNaN(inr)) return "—";
  if (Math.abs(inr) >= 1e7) return formatInrCrore(inr);
  if (Math.abs(inr) >= 1e5) return `₹${(inr / 1e5).toLocaleString("en-IN", { maximumFractionDigits: 2 })} L`;
  return `₹${inr.toLocaleString("en-IN")}`;
}

const IST: Intl.DateTimeFormatOptions = { timeZone: "Asia/Kolkata" };

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-IN", { ...IST, day: "2-digit", month: "short", year: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toLocaleString("en-IN", {
    ...IST, day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  })} IST`;
}

export function daysUntil(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return null;
  return Math.ceil((d - Date.now()) / 86400000);
}

export function formatScore(score: number | null | undefined): string {
  if (score === null || score === undefined) return "—";
  return score.toFixed(2);
}

export function humanize(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function spanLabel(s: SourceSpan | null | undefined): string {
  if (!s) return "—";
  if (s.page !== null && s.page !== undefined) return `${s.doc_id} · p.${s.page}`;
  if (s.sheet) return `${s.doc_id} · ${s.sheet}${s.cell ? `!${s.cell}` : ""}`;
  return s.doc_id;
}

export type Tone = "green" | "amber" | "red" | "blue" | "slate" | "violet";

export const toneClasses: Record<Tone, string> = {
  green: "bg-emerald-50 text-emerald-800 ring-emerald-600/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/20",
  red: "bg-red-50 text-red-800 ring-red-600/20",
  blue: "bg-sky-50 text-sky-800 ring-sky-600/20",
  slate: "bg-slate-100 text-slate-700 ring-slate-500/20",
  violet: "bg-violet-50 text-violet-800 ring-violet-600/20",
};

const STATUS_TONES: Record<string, Tone> = {
  // eligibility
  meets: "green",
  meets_with_undertaking: "green",
  meets_with_substitution: "green",
  needs_action: "amber",
  partial: "amber",
  needs_human: "violet",
  gap: "red",
  // risk
  within_policy: "green",
  review: "amber",
  escalate: "red",
  // recommendation
  BID: "green",
  BID_WITH_CONDITIONS: "amber",
  NO_BID: "red",
  // approvals
  pending: "amber",
  approved: "green",
  rejected: "red",
  changes_requested: "amber",
  resuming: "blue",
  superseded: "slate",
  review_required: "violet",
  not_required: "slate",
  // ingestion / runs
  uploaded: "slate",
  validating: "blue",
  parsing: "blue",
  indexed: "green",
  failed: "red",
  quarantined: "red",
  queued: "slate",
  running: "blue",
  awaiting_human: "violet",
  completed: "green",
  cancelled: "slate",
  not_started: "slate",
  // tender
  created: "slate",
  ingesting: "blue",
  ready_for_analysis: "blue",
  analyzing: "blue",
  awaiting_bid_decision: "violet",
  bid_approved: "green",
  no_bid_approved: "red",
  drafting: "blue",
  awaiting_draft_review: "violet",
  exported: "green",
  amendment_pending: "amber",
  reanalysis_required: "amber",
  reanalyzing: "blue",
  // verifier
  supported: "green",
  unsupported: "red",
  contradicted: "red",
  conditional: "amber",
  unverifiable: "violet",
  // amendments
  diff_ready: "violet",
  confirmed: "green",
  parsed: "blue",
  // severity
  low: "slate",
  medium: "amber",
  high: "red",
  critical: "red",
  blocking: "red",
};

export function statusTone(status: string | null | undefined): Tone {
  if (!status) return "slate";
  return STATUS_TONES[status] ?? "slate";
}

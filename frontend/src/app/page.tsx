"use client";

import { ArrowUpRight, Building2, CalendarClock, FileStack, FolderKanban, Gavel, PlusCircle, ShieldAlert } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Badge, Button, Empty, ErrorBanner, Spinner } from "@/components/ui";
import { usePoll } from "@/hooks/use-poll";
import { api } from "@/lib/api";
import { cn, daysUntil, formatDateTime, formatScore, statusTone } from "@/lib/formatting";
import type { TenderView } from "@/lib/types";

const RAIL = { green: "bg-olive", amber: "bg-tobacco", red: "bg-merlot" } as Record<string, string>;

function Metric({ icon, label, value, hint, accent }: {
  icon: ReactNode; label: string; value: ReactNode; hint?: ReactNode; accent?: boolean;
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-card">
      <span className={cn("grid size-9 shrink-0 place-items-center rounded-lg",
        accent ? "bg-tobacco/10 text-tobacco" : "bg-slate-100 text-slate-700")}>{icon}</span>
      <div className="min-w-0">
        <div className="text-xs font-medium text-slate-500">{label}</div>
        <div className="font-display text-xl font-semibold text-slate-900">{value}</div>
        {hint && <div className="truncate text-xs text-slate-500">{hint}</div>}
      </div>
    </div>
  );
}

function TenderCard({ t }: { t: TenderView }) {
  const days = daysUntil(t.submissionDeadline);
  const a = t.latestAssessment;
  const soon = days !== null && days >= 0 && days <= 14;
  return (
    <Link href={`/tenders/${t.tenderId}`}
      className="group relative flex flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card transition hover:-translate-y-px hover:shadow-lift">
      <span className={cn("absolute inset-y-0 left-0 w-1", a ? RAIL[statusTone(a.recommendation)] : "bg-slate-200")} />
      <div className="flex items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <div className="text-xs text-slate-500">{t.tenderId}{t.referenceNo && <> · {t.referenceNo}</>}</div>
          <h3 className="mt-1 truncate text-base font-semibold">{t.title}</h3>
          {t.buyer && <div className="mt-0.5 flex items-center gap-1.5 text-sm text-slate-500">
            <Building2 className="size-3.5" /> {t.buyer}</div>}
        </div>
        <Badge solid status={t.status} />
      </div>
      <dl className="mx-5 mt-4 grid grid-cols-3 gap-4 border-t border-slate-200 pt-3 text-sm">
        <div><dt className="text-xs text-slate-500">Recommendation</dt>
          <dd className="mt-1">{a ? <Badge status={a.recommendation} /> : <span className="text-slate-400">Not analysed</span>}</dd></div>
        <div><dt className="text-xs text-slate-500">Score</dt>
          <dd className="mt-0.5 font-display text-lg font-semibold text-slate-900">{a ? formatScore(a.score) : "—"}</dd></div>
        <div><dt className="text-xs text-slate-500">Gate 1</dt><dd className="mt-1"><Badge status={t.approvalStatus} /></dd></div>
      </dl>
      <div className="mt-4 flex items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-5 py-2.5 text-xs">
        <span className={cn("flex items-center gap-1.5", soon ? "font-medium text-tobacco" : "text-slate-500")}>
          <CalendarClock className="size-3.5" />
          {t.submissionDeadline ? <>Due {formatDateTime(t.submissionDeadline)}
            {days !== null && ` · ${days >= 0 ? `${days} days left` : `closed ${-days} days ago`}`}</> : "No deadline yet"}
        </span>
        <span className="flex items-center gap-1 text-slate-500 group-hover:text-slate-900">
          v{t.currentVersion} <ArrowUpRight className="size-3.5" /></span>
      </div>
    </Link>
  );
}

export default function Dashboard() {
  const tenders = usePoll(() => api.listTenders(), [], { intervalMs: 5000 });
  const kb = usePoll(() => api.kbStatus(), []);
  const items = tenders.data?.items ?? [];
  const awaiting = items.filter((t) => t.approvalStatus === "pending" && t.latestAssessment).length;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Tenders</h1>
          {tenders.data && <p className="mt-0.5 text-sm text-slate-500">
            {items.length} {items.length === 1 ? "tender" : "tenders"}{awaiting > 0 && ` · ${awaiting} awaiting a bid decision`}</p>}
        </div>
        <Link href="/tenders/new"><Button><PlusCircle className="size-4" /> New tender</Button></Link>
      </div>

      <ErrorBanner error={kb.error} />
      {kb.data && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Metric icon={<Gavel className="size-4" />} label="Awaiting bid decision" value={awaiting}
            hint={`${items.length} ${items.length === 1 ? "tender" : "tenders"} in total`} accent={awaiting > 0} />
          <Metric icon={<FileStack className="size-4" />} label="Knowledge base documents" value={kb.data.documents}
            hint={`${kb.data.chunks} searchable passages`} />
          <Metric icon={<FolderKanban className="size-4" />} label="Reference projects" value={kb.data.facts.projects ?? 0}
            hint={`${kb.data.facts.people ?? 0} people on record`} />
          <Metric icon={<ShieldAlert className="size-4" />} label="Credential warnings" value={kb.data.warnings.length}
            hint={kb.data.warnings[0] ?? "All credentials valid"} accent={kb.data.warnings.length > 0} />
        </div>
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-slate-700">Active tenders</h2>
        <ErrorBanner error={tenders.error} />
        {tenders.loading && !tenders.data && <Spinner />}
        {tenders.data && items.length === 0 && (
          <Empty>No tenders yet. Create one and upload the original tender pack.</Empty>
        )}
        <div className="grid gap-4 lg:grid-cols-2">
          {items.map((t) => <TenderCard key={t.tenderId} t={t} />)}
        </div>
      </section>
    </div>
  );
}

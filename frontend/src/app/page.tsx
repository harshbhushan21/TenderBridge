"use client";

import { CalendarClock, FileText, PlusCircle } from "lucide-react";
import Link from "next/link";

import { Badge, Button, Card, Empty, ErrorBanner, Spinner, Stat } from "@/components/ui";
import { usePoll } from "@/hooks/use-poll";
import { api } from "@/lib/api";
import { daysUntil, formatDateTime, formatScore } from "@/lib/formatting";

export default function Dashboard() {
  const tenders = usePoll(() => api.listTenders(), [], { intervalMs: 5000 });
  const kb = usePoll(() => api.kbStatus(), []);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Tenders</h1>
        </div>
        <Link href="/tenders/new"><Button><PlusCircle className="size-4" /> New tender</Button></Link>
      </div>

      <Card title="Company knowledge base">
        {kb.loading && !kb.data ? <Spinner /> : <ErrorBanner error={kb.error} />}
        {kb.data && (
          <div className="flex flex-wrap items-start gap-8">
            <Stat label="Status" value={<Badge status={kb.data.status === "ready" ? "indexed" : kb.data.status}>
              {kb.data.status}</Badge>} />
            <Stat label="Documents" value={kb.data.documents} hint={`${kb.data.chunks} searchable chunks`} />
            <Stat label="Projects / people" value={`${kb.data.facts.projects ?? 0} / ${kb.data.facts.people ?? 0}`} />
            <div className="min-w-64 flex-1">
              <div className="text-xs font-medium uppercase tracking-wide text-slate-500">Warnings</div>
              <ul className="mt-1 space-y-1 text-sm">
                {kb.data.warnings.length === 0 && <li className="text-slate-500">None</li>}
                {kb.data.warnings.map((w) => (
                  <li key={w} className="flex items-center gap-2 text-amber-800"><CalendarClock className="size-4" /> {w}</li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </Card>

      <ErrorBanner error={tenders.error} />
      {tenders.loading && !tenders.data && <Spinner />}
      {tenders.data && tenders.data.items.length === 0 && (
        <Empty>No tenders yet. Create one and upload the original tender pack.</Empty>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {tenders.data?.items.map((t) => {
          const days = daysUntil(t.submissionDeadline);
          return (
            <Link key={t.tenderId} href={`/tenders/${t.tenderId}`}
              className="block rounded-lg border border-slate-200 bg-white p-4 shadow-sm hover:border-slate-400">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-xs text-slate-500">
                    <FileText className="size-3.5" /> {t.tenderId} · v{t.currentVersion}
                    {t.referenceNo && <> · {t.referenceNo}</>}
                  </div>
                  <h3 className="mt-1 truncate font-medium">{t.title}</h3>
                </div>
                <Badge status={t.status} />
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
                {t.latestAssessment ? (
                  <>
                    <Badge status={t.latestAssessment.recommendation} />
                    <span className="font-semibold">{formatScore(t.latestAssessment.score)}</span>
                    <span className="text-slate-500">v{t.latestAssessment.version}</span>
                  </>
                ) : <span className="text-slate-500">Not analysed yet</span>}
                <span className="text-slate-400">·</span>
                <span className="text-slate-600">Gate 1: <Badge status={t.approvalStatus} /></span>
              </div>
              {t.submissionDeadline && (
                <p className="mt-2 text-xs text-slate-500">
                  Bid due {formatDateTime(t.submissionDeadline)}
                  {days !== null && ` (${days >= 0 ? `${days} days left` : `${-days} days ago`})`}
                </p>
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

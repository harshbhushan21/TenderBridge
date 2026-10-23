"use client";

import { ArrowRight } from "lucide-react";

import { Badge, Card, Empty, ErrorBanner, Spinner } from "@/components/ui";
import { usePoll } from "@/hooks/use-poll";
import { api } from "@/lib/api";
import { formatDateTime, formatScore, humanize } from "@/lib/formatting";
import type { CompareResponse, TenderView } from "@/lib/types";

export function VersionsTab({ tender }: { tender: TenderView }) {
  const versions = usePoll(() => api.versions(tender.tenderId), [tender.tenderId, tender.currentVersion, tender.status]);
  const analysed = (versions.data?.versions ?? []).filter((v) => v.assessment);
  const canCompare = analysed.length >= 2;
  const cmp = usePoll<CompareResponse | null>(() => canCompare
    ? api.compare(tender.tenderId, analysed[0].version, analysed[analysed.length - 1].version) : Promise.resolve(null),
  [canCompare, analysed.length, tender.status]);

  return (
    <div className="space-y-4">
      <ErrorBanner error={versions.error ?? cmp.error} />
      {versions.loading && !versions.data && <Spinner />}
      <div className="grid gap-3 md:grid-cols-2">
        {versions.data?.versions.map((v) => (
          <Card key={v.version} title={`Version ${v.version}`} actions={<Badge status={v.status === "effective" ? "approved" : "superseded"}>{v.status}</Badge>}>
            <div className="space-y-1 text-sm">
              {v.assessment ? (
                <div className="flex items-center gap-3"><Badge status={v.assessment.recommendation} />
                  <span className="font-semibold">{formatScore(v.assessment.score)}</span>
                  <span className="text-slate-500">Gate 1:</span><Badge status={v.assessment.approval_status} /></div>
              ) : <p className="text-slate-500">Not analysed{v.run_status ? ` (${humanize(v.run_status)})` : ""}.</p>}
              {v.confirmed_at && <p className="text-xs text-slate-500">Confirmed by {v.confirmed_by} on {formatDateTime(v.confirmed_at)}</p>}
            </div>
          </Card>
        ))}
      </div>
      {!canCompare && versions.data && <Empty>Comparison appears once two versions have been analysed.</Empty>}
      {cmp.data?.a && cmp.data?.b && (
        <Card title={`What changed: v${cmp.data.a.version} → v${cmp.data.b.version}`}>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <Badge status={cmp.data.a.recommendation} /> {formatScore(cmp.data.a.score)}
            <ArrowRight className="size-4 text-slate-400" />
            <Badge status={cmp.data.b.recommendation} /> {formatScore(cmp.data.b.score)}
          </div>
          <p className="mt-2 text-xs text-slate-500">A higher score can still mean NO_BID: hard gates decide first.</p>
          <h3 className="mt-4 text-xs font-semibold uppercase text-slate-500">Verdicts that changed</h3>
          <ul className="mt-1 space-y-2 text-sm">
            {cmp.data.changed_items.filter((c) => c.hard_gate).map((c) => (
              <li key={c.requirement_id} className="rounded-md border border-slate-200 p-2">
                <div className="flex items-center gap-2"><span className="font-medium">{c.requirement_id}</span>
                  <Badge status={c.before?.status} /><ArrowRight className="size-3.5" /><Badge status={c.after?.status} /></div>
                <p className="clause mt-1 text-slate-600">{c.after?.summary}</p>
              </li>
            ))}
          </ul>
          <h3 className="mt-4 text-xs font-semibold uppercase text-slate-500">Contract terms that changed</h3>
          <ul className="mt-1 space-y-1 text-sm">
            {cmp.data.risk_changes.map((r) => (
              <li key={r.category} className="flex flex-wrap items-center gap-2">{humanize(r.category)}:
                <Badge status={r.before} /><ArrowRight className="size-3.5" /><Badge status={r.after} />
                <span className="text-xs text-slate-500">{r.tender_value}</span></li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

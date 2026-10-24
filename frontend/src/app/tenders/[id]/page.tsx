"use client";

import { Building2, CalendarClock, ChevronRight, Download, Hash, Layers } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Badge, Card, ErrorBanner, Spinner, Tabs } from "@/components/ui";
import { ActivityTab } from "@/components/workspace/activity";
import { AmendmentPanel } from "@/components/workspace/amendments";
import { DraftsTab } from "@/components/workspace/drafts";
import { EvidencePanel } from "@/components/workspace/evidence-panel";
import { NodeStrip } from "@/components/workspace/node-strip";
import { Overview } from "@/components/workspace/overview";
import { RequirementsMatrix } from "@/components/workspace/requirements";
import { RisksTable } from "@/components/workspace/risks";
import { VersionsTab } from "@/components/workspace/versions";
import { usePoll } from "@/hooks/use-poll";
import { api } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/formatting";
import type { ComplianceItem } from "@/lib/types";

type Tab = "overview" | "requirements" | "risks" | "draft" | "documents" | "versions" | "activity";

/** Results for the current version; a missing result (not analysed yet) is null, not an error. */
async function loadResults(id: string, version: number) {
  const soft = <T,>(p: Promise<T>) => p.catch(() => null);
  const [assessment, keyFacts, compliance, risks, requirements, ingestion] = await Promise.all([
    soft(api.assessment(id, version)), soft(api.keyFacts(id, version)), soft(api.compliance(id, version)),
    soft(api.risks(id, version)), soft(api.requirements(id, { version })), soft(api.ingestion(id)),
  ]);
  return {
    assessment, keyFacts,
    compliance: compliance?.items ?? [], risks: risks?.items ?? [], requirements: requirements?.items ?? [],
    files: ingestion?.files ?? [],
  };
}

export default function TenderWorkspace() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState<Tab>("overview");
  const [open, setOpen] = useState<ComplianceItem | null>(null);
  const tender = usePoll(() => api.getTender(id), [id], { intervalMs: 4000 });
  const t = tender.data;
  const running = t?.analysisStatus === "running";
  const results = usePoll(() => (t ? loadResults(id, t.currentVersion) : Promise.resolve(null)),
    [id, t?.currentVersion, t?.analysisStatus, t?.approvalStatus, t?.latestRunId]);

  if (!t) {
    return tender.error ? <ErrorBanner error={tender.error} /> : <Spinner label="Loading tender…" />;
  }
  const r = results.data;
  const fileNames = Object.fromEntries((r?.files ?? []).map((f) => [f.doc_id, f.filename]));
  const refresh = () => { tender.reload(); results.reload(); };

  return (
    <div className="space-y-5">
      <header className="space-y-3">
        <nav className="flex items-center gap-1 text-xs text-slate-500">
          <Link href="/" className="hover:text-slate-900">Tenders</Link>
          <ChevronRight className="size-3.5" /> <span className="text-slate-700">{t.tenderId}</span>
        </nav>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 className="text-2xl font-semibold">{t.title}</h1>
          <div className="flex items-center gap-2">
            {t.amendmentPending && t.status !== "amendment_pending" && <Badge tone="amber">Corrigendum pending</Badge>}
            <Badge solid status={t.status}>{humanize(t.status)}</Badge>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm text-slate-600">
          {t.buyer && <span className="flex items-center gap-1.5"><Building2 className="size-4 text-slate-400" /> {t.buyer}</span>}
          {t.referenceNo && <span className="flex items-center gap-1.5"><Hash className="size-4 text-slate-400" /> {t.referenceNo}</span>}
          <span className="flex items-center gap-1.5"><Layers className="size-4 text-slate-400" /> Version {t.currentVersion}</span>
          {t.submissionDeadline && <span className="flex items-center gap-1.5">
            <CalendarClock className="size-4 text-slate-400" /> Bids due {formatDateTime(t.submissionDeadline)}</span>}
        </div>
      </header>

      {t.latestRunId && (running || t.analysisStatus === "awaiting_human") && (
        <NodeStrip tenderId={id} runId={t.latestRunId} onFinished={refresh} />
      )}

      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "overview", label: "Overview" },
        { id: "requirements", label: `Requirements${r ? ` (${r.compliance.length})` : ""}` },
        { id: "risks", label: "Risks" },
        { id: "draft", label: t.draftStatus === "awaiting_review" ? "Response draft · review" : "Response draft" },
        { id: "documents", label: "Documents & corrigenda" },
        { id: "versions", label: "Versions" },
        { id: "activity", label: "Activity" },
      ]} />

      {running && !r?.assessment && <Spinner label="Analysis running…" />}
      {tab === "overview" && r && (
        <Overview tender={t} assessment={r.assessment} keyFacts={r.keyFacts} compliance={r.compliance}
          onOpen={setOpen} onDecided={refresh} />
      )}
      {tab === "requirements" && r && (
        <RequirementsMatrix items={r.compliance} onOpen={setOpen}
          requirements={Object.fromEntries(r.requirements.map((q) => [q.requirement_id, q]))} />
      )}
      {tab === "risks" && r && <RisksTable risks={r.risks} />}
      {tab === "documents" && (
        <div className="space-y-4">
          <Card title="Tender files">
            <ul className="divide-y divide-slate-100 text-sm">
              {r?.files.map((f) => (
                <li key={f.doc_id} className="flex flex-wrap items-center gap-3 py-2">
                  <span className="font-medium">{f.filename}</span>
                  <Badge tone="slate">{humanize(f.doc_role)}</Badge>
                  <Badge status={f.status} />
                  {f.page_count != null && <span className="text-xs text-slate-500">{f.page_count} pages</span>}
                  <a className="ml-auto text-slate-500 hover:text-slate-900" href={api.fileDownloadUrl(id, f.doc_id)}
                    title="Download original"><Download className="size-4" /></a>
                </li>
              ))}
            </ul>
          </Card>
          <AmendmentPanel tender={t} onChanged={refresh} onReanalysed={refresh} />
        </div>
      )}
      {tab === "draft" && <DraftsTab tender={t} onChanged={refresh} />}
      {tab === "versions" && <VersionsTab tender={t} />}
      {tab === "activity" && <ActivityTab tenderId={id} />}

      {open && (
        <EvidencePanel tenderId={id} item={open} fileNames={fileNames} onClose={() => setOpen(null)}
          requirement={r?.requirements.find((q) => q.requirement_id === open.requirement_id)} />
      )}
    </div>
  );
}

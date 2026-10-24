"use client";

import { CheckCircle2, Gavel, PauseCircle, XCircle } from "lucide-react";
import { useState } from "react";

import { Badge, Button, Card, ErrorBanner, Stat } from "@/components/ui";
import { useRole } from "@/hooks/use-role";
import { api, currentUser, DEMO_IDENTITIES, errorMessage } from "@/lib/api";
import { formatDateTime, formatInr, formatScore, humanize } from "@/lib/formatting";
import type { BidAssessment, ComplianceItem, KeyFacts, TenderView } from "@/lib/types";

export function Overview({ tender, assessment, keyFacts, compliance, onOpen, onDecided }: {
  tender: TenderView; assessment: BidAssessment | null; keyFacts: KeyFacts | null;
  compliance: ComplianceItem[]; onOpen: (item: ComplianceItem) => void; onDecided: () => void;
}) {
  if (!assessment) {
    return <Card title="Assessment"><p className="text-sm text-slate-500">No assessment for v{tender.currentVersion} yet.
      {tender.status === "reanalysis_required" && " The corrigendum was confirmed: re-analyse from the Documents tab."}</p></Card>;
  }
  const gates = compliance.filter((c) => c.hard_gate);
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <Card title={`System recommendation · v${assessment.tender_version}`}>
          <div className="flex flex-wrap items-center gap-6">
            <Badge status={assessment.recommendation} className="px-3 py-1 text-sm" />
            <Stat label="Weighted score" value={formatScore(assessment.score)} />
            <Stat label="Hard-gate failures" value={assessment.hard_gate_failures.length || "None"} />
          </div>
          {assessment.hard_gate_failures.length > 0 && (
            <p className="mt-3 rounded-md bg-red-50 p-2 text-sm text-red-800">
              A failed hard gate means NO_BID whatever the score ({assessment.hard_gate_failures.join(", ")}).
            </p>
          )}
          <div className="mt-4 space-y-2">
            {assessment.criteria.map((c) => (
              <div key={c.key}>
                <div className="flex justify-between text-xs"><span>{c.label} · {c.weight.toFixed(0)}%</span>
                  <span className="font-medium">{c.raw_score.toFixed(2)}</span></div>
                <div className="h-1.5 rounded bg-slate-100"><div className="h-1.5 rounded bg-slate-700"
                  style={{ width: `${Math.min(100, c.raw_score)}%` }} /></div>
              </div>
            ))}
            <p className="text-xs text-slate-500">Strategic fit, technical capability and delivery capacity are demo
              estimates configured by the bid team, not computed from documents.</p>
          </div>
        </Card>
        <Card title={`Hard gates (${gates.length})`}>
          <ul className="divide-y divide-slate-100">
            {gates.map((g) => (
              <li key={g.requirement_id}>
                <button onClick={() => onOpen(g)} className="flex w-full items-start gap-3 py-2 text-left hover:bg-slate-50">
                  <span className="w-20 shrink-0 text-xs font-medium text-slate-500">{g.requirement_id.replace("REQ-", "")}</span>
                  <span className="clause flex-1 text-sm">{g.summary}</span>
                  <span className="flex shrink-0 flex-col items-end gap-1">
                    <Badge status={g.status} />
                    {g.reused_from_version && <span className="text-[10px] text-slate-400">reused v{g.reused_from_version}</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      </div>
      <div className="space-y-4">
        <Gate1Panel tender={tender} assessment={assessment} onDecided={onDecided} />
        {keyFacts && (
          <Card title="Key facts">
            <dl className="space-y-2 text-sm">
              <Fact label="Bid submission" value={formatDateTime(keyFacts.submission_deadline)} />
              <Fact label="Pre-bid meeting" value={formatDateTime(keyFacts.prebid_meeting)} />
              <Fact label="Bid opening" value={formatDateTime(keyFacts.bid_opening)} />
              <Fact label="EMD" value={keyFacts.emd ? formatInr(keyFacts.emd.amount_inr) : "—"} />
              <Fact label="PBG" value={keyFacts.pbg_percent != null ? `${keyFacts.pbg_percent}%` : "—"} />
              <Fact label="Payment" value={keyFacts.payment_terms ?? "—"} />
              <Fact label="SLA penalty cap" value={keyFacts.penalty_cap_percent != null ? `${keyFacts.penalty_cap_percent}%` : "—"} />
              <Fact label="Evaluation" value={keyFacts.evaluation_method ?? "—"} />
            </dl>
          </Card>
        )}
        {assessment.conditions.length > 0 && (
          <Card title="Conditions to bid">
            <ul className="list-disc space-y-1 pl-5 text-sm">{assessment.conditions.map((c) => <li key={c}>{c}</li>)}</ul>
          </Card>
        )}
      </div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="flex justify-between gap-3"><dt className="text-slate-500">{label}</dt><dd className="text-right">{value}</dd></div>;
}

function Gate1Panel({ tender, assessment, onDecided }: {
  tender: TenderView; assessment: BidAssessment; onDecided: () => void;
}) {
  const role = useRole();
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const waiting = tender.analysisStatus === "awaiting_human" && tender.approvalStatus === "pending";

  async function decide(action: "approve_bid" | "no_bid" | "defer") {
    setBusy(action);
    setError(null);
    try {
      await api.decide(tender.tenderId, { tender_version: assessment.tender_version, action, reviewer: currentUser(),
        comment: comment || null, conditions_accepted: action === "approve_bid" ? assessment.conditions : [] });
      setComment("");
      onDecided();
    } catch (e) {
      setError(errorMessage(e) + (role === "analyst" ? " (the refusal is recorded in the audit trail)" : ""));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card title={<span className="flex items-center gap-2"><Gavel className="size-4" /> Gate 1: human decision</span>}
      actions={<Badge status={tender.approvalStatus} />}>
      <p className="text-sm text-slate-600">
        The system recommends <strong>{humanize(assessment.recommendation)}</strong>. Only a Bid Manager can decide;
        the decision is bound to v{assessment.tender_version}.
      </p>
      {waiting ? (
        <div className="mt-3 space-y-3">
          <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2}
            placeholder="Reason (recorded in the audit trail)"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm" />
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => decide("approve_bid")} loading={busy === "approve_bid"}>
              <CheckCircle2 className="size-4" /> Approve bid</Button>
            <Button variant="danger" onClick={() => decide("no_bid")} loading={busy === "no_bid"}>
              <XCircle className="size-4" /> No bid</Button>
            <Button variant="secondary" onClick={() => decide("defer")} loading={busy === "defer"}>
              <PauseCircle className="size-4" /> Defer</Button>
          </div>
          <p className="text-xs text-slate-500">Acting as {DEMO_IDENTITIES[role].label} ({DEMO_IDENTITIES[role].user}).</p>
          <ErrorBanner error={error} />
        </div>
      ) : (
        <p className="mt-3 text-sm text-slate-500">
          {tender.approvalStatus === "pending" ? "Waiting for the analysis to reach Gate 1." :
            `Decision recorded: ${humanize(tender.approvalStatus)}.${tender.approvalStatus === "approved"
              ? " Next: draft the response section in the Response draft tab." : ""}`}
        </p>
      )}
    </Card>
  );
}

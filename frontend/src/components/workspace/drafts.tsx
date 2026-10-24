"use client";

import { CheckCircle2, Download, FileText, MessageSquareWarning, Pencil, XCircle } from "lucide-react";
import { Fragment, useMemo, useState } from "react";

import { Badge, Button, Callout, Card, Empty, ErrorBanner, Spinner } from "@/components/ui";
import { NodeStrip } from "@/components/workspace/node-strip";
import { usePoll } from "@/hooks/use-poll";
import { useRole } from "@/hooks/use-role";
import { api, errorMessage } from "@/lib/api";
import { cn, humanize, spanLabel } from "@/lib/formatting";
import { DRAFT_NODE_LABELS, DRAFT_NODE_ORDER, type DraftReview, type SectionDraft, type SourceSpan,
  type TenderView } from "@/lib/types";

const ACTIVE = new Set(["queued", "running", "resuming"]);

/** Sources numbered in first-use order, exactly as the [n] markers and the DOCX source list. */
function numberedSources(draft: SectionDraft): SourceSpan[] {
  const seen = new Map<string, SourceSpan>();
  for (const claim of draft.claims) {
    for (const s of claim.citations) {
      const key = `${s.doc_id}|${s.page}|${(s.text_span || "").slice(0, 60)}`;
      if (!seen.has(key)) seen.set(key, s);
    }
  }
  return [...seen.values()];
}

export function DraftsTab({ tender, onChanged }: { tender: TenderView; onChanged: () => void }) {
  const role = useRole();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const drafts = usePoll(() => api.drafts(tender.tenderId), [tender.tenderId, tender.currentVersion, tender.draftStatus],
    { intervalMs: tender.draftStatus === "drafting" ? 1500 : 0 });
  const run = drafts.data?.run;
  const draft = drafts.data?.items[0];

  async function start() {
    setStarting(true);
    setError(null);
    try {
      await api.startDrafting(tender.tenderId);
      onChanged();
      await drafts.reload();
    } catch (e) {
      setError(errorMessage(e) + (role === "analyst" ? " (the refusal is recorded in the audit trail)" : ""));
    } finally {
      setStarting(false);
    }
  }

  if (tender.approvalStatus !== "approved") {
    return (
      <Card title="Response draft">
        <p className="text-sm text-slate-500">Drafting starts after a bid manager approves the bid at Gate 1 for
          v{tender.currentVersion}. A No-Bid decision produces the No-Bid report instead.</p>
      </Card>
    );
  }
  const startCard = (
    <Card title="Draft the response section">
      <p className="mb-3 text-sm text-slate-600">TenderBridge drafts <em>Approach to Data Centre Operations and Security</em>
        (Format T-1 §2 and §4) from company documents approved for reuse. Every sentence cites its source and is checked
        by the verifier; unsupported statements are removed before you review it at Gate 2.</p>
      <ErrorBanner error={error} />
      <Button onClick={start} loading={starting}><FileText className="size-4" /> Draft the response</Button>
    </Card>
  );
  if (drafts.loading && !drafts.data) return <Spinner />;
  if (!run) return startCard;
  return (
    <div className="space-y-4">
      <ErrorBanner error={drafts.error} />
      {(ACTIVE.has(run.status) || run.status === "awaiting_human") && (
        <NodeStrip tenderId={tender.tenderId} runId={run.run_id} nodes={DRAFT_NODE_ORDER} labels={DRAFT_NODE_LABELS}
          onFinished={() => { onChanged(); void drafts.reload(); }} />
      )}
      {ACTIVE.has(run.status) && !draft && <Spinner label="Drafting from approved company evidence…" />}
      {run.status === "failed" && <ErrorBanner error={`Drafting failed: ${run.error ?? "unknown error"}`} />}
      {draft && <DraftReviewView tender={tender} draft={draft} runStatus={run.status}
        onReviewed={() => { onChanged(); void drafts.reload(); }} />}
      {draft && run.status === "completed" && draft.status !== "approved" && startCard}
    </div>
  );
}

function DraftReviewView({ tender, draft, runStatus, onReviewed }: {
  tender: TenderView; draft: SectionDraft; runStatus: string; onReviewed: () => void;
}) {
  const role = useRole();
  const sources = useMemo(() => numberedSources(draft), [draft]);
  const [selected, setSelected] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [editing, setEditing] = useState(false);
  const [edited, setEdited] = useState(draft.body_markdown);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const verdicts = new Map((draft.verifier?.verdicts ?? []).map((v) => [v.claim_id, v]));
  const reviewable = runStatus === "awaiting_human" && draft.status === "pending" && !draft.stale;

  async function decide(action: DraftReview["action"]) {
    setBusy(action);
    setError(null);
    try {
      await api.reviewDraft(draft.draft_id, { action, comment: comment || undefined,
        edited_markdown: action === "edit" ? edited : undefined });
      setEditing(false);
      onReviewed();
    } catch (e) {
      setError(errorMessage(e) + (role === "analyst" ? " (the refusal is recorded in the audit trail)" : ""));
    } finally {
      setBusy(null);
    }
  }

  // "text [1, 2] text" -> text and clickable source markers
  const body = draft.human_edited ? [draft.body_markdown] : draft.body_markdown.split(/(\[\d+(?:,\s*\d+)*\])/);
  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <div className="space-y-4 lg:col-span-3">
        <Card title={draft.title} actions={<div className="flex items-center gap-2">
          <Badge status={draft.status} />{draft.verifier?.passed && <Badge tone="green">verified</Badge>}</div>}>
          <p className="mb-3 text-xs text-slate-500">Revision {draft.revision} · {draft.generated_by ?? "draft"} ·
            {" "}{draft.evidence_count ?? sources.length} approved passages retrieved, {sources.length} cited · v{draft.tender_version}</p>
          {draft.stale && <Callout tone="amber" className="mb-3">This draft belongs to a
            superseded tender version and cannot be approved.</Callout>}
          {editing ? (
            <textarea value={edited} onChange={(e) => setEdited(e.target.value)} rows={12}
              className="w-full rounded-md border border-slate-300 p-2 font-mono text-sm" />
          ) : (
            <p className="clause leading-7 text-slate-800">
              {body.map((part, i) => {
                const m = part.match(/^\[(\d+(?:,\s*\d+)*)\]$/);
                if (!m) return <Fragment key={i}>{part}</Fragment>;
                return <span key={i}>[{m[1].split(",").map((n, j) => (
                  <Fragment key={n}>{j > 0 && ", "}<button onClick={() => setSelected(Number(n))}
                    className={cn("font-semibold text-sky-700 hover:underline", selected === Number(n) && "bg-sky-100")}>
                    {n.trim()}</button></Fragment>))}]</span>;
              })}
            </p>
          )}
          {draft.human_edited && <p className="mt-2 text-xs text-slate-500">Edited by the reviewer at Gate 2: the edited
            text is the reviewer&apos;s responsibility and was not re-verified.</p>}
          {(draft.placeholders.length > 0 || (draft.removed_claims ?? []).length > 0) && (
            <Callout tone="amber" className="mt-3">
              {draft.placeholders.map((p) => <p key={p}>{p}</p>)}
              {(draft.removed_claims ?? []).map((c) => (
                <p key={c.text} className="mt-1 text-xs"><span className="line-through">{c.text}</span> — {c.reason}</p>))}
            </Callout>
          )}
        </Card>

        <Card title="Claims checked by the verifier">
          {draft.claims.length === 0 ? <Empty>No claims survived verification.</Empty> : (
            <ul className="space-y-2 text-sm">
              {draft.claims.map((c) => {
                const v = verdicts.get(c.claim_id);
                return (
                  <li key={c.claim_id} className="flex items-start gap-2">
                    <Badge status={v?.verdict === "supported" ? "meets" : v?.verdict === "conditional" ? "needs_action" : "gap"}>
                      {v?.verdict ?? "unchecked"}</Badge>
                    <div><p>{c.text}</p><p className="text-xs text-slate-500">{v?.reason}</p></div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card title="Gate 2: human review">
          {reviewable ? (
            <div className="space-y-3">
              <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment (audit trail; used as feedback for changes)"
                className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
              <div className="flex flex-wrap gap-2">
                {editing ? (
                  <>
                    <Button onClick={() => decide("edit")} loading={busy === "edit"} disabled={!edited.trim()}>
                      <CheckCircle2 className="size-4" /> Save edit and approve</Button>
                    <Button variant="secondary" onClick={() => { setEditing(false); setEdited(draft.body_markdown); }}>Cancel</Button>
                  </>
                ) : (
                  <>
                    <Button onClick={() => decide("approve")} loading={busy === "approve"}><CheckCircle2 className="size-4" /> Approve</Button>
                    <Button variant="secondary" onClick={() => setEditing(true)}><Pencil className="size-4" /> Edit</Button>
                    <Button variant="secondary" onClick={() => decide("request_changes")} loading={busy === "request_changes"}>
                      <MessageSquareWarning className="size-4" /> Request changes</Button>
                    <Button variant="danger" onClick={() => decide("reject")} loading={busy === "reject"}><XCircle className="size-4" /> Reject</Button>
                  </>
                )}
              </div>
              <ErrorBanner error={error} />
              <p className="text-xs text-slate-500">Only a Bid Manager can decide; the decision is bound to v{tender.currentVersion}.</p>
            </div>
          ) : (
            <div className="space-y-2 text-sm">
              <p className="text-slate-600">Decision: <Badge status={draft.status} />{draft.review?.comment ? ` · "${draft.review.comment}"` : ""}</p>
              {draft.status === "approved" && (
                <a href={api.exportUrl(tender.tenderId, "draft_docx", draft.tender_version)}
                  className="inline-flex items-center gap-1 font-medium text-sky-700 hover:underline">
                  <Download className="size-4" /> Download the approved section (DOCX)</a>
              )}
              {runStatus !== "completed" && draft.status !== "pending" && <Spinner label="Applying the decision…" />}
            </div>
          )}
        </Card>
      </div>

      <Card title={`Sources (${sources.length})`} className="lg:col-span-2">
        <ol className="space-y-3 text-sm">
          {sources.map((s, i) => (
            <li key={`${s.doc_id}-${i}`} onClick={() => setSelected(i + 1)}
              className={cn("cursor-pointer rounded-md border p-2", selected === i + 1 ? "border-sky-400 bg-sky-50" : "border-slate-200")}>
              <div className="text-xs font-medium text-slate-700">[{i + 1}] {spanLabel(s)}</div>
              <p className="clause mt-1 text-xs text-slate-600">{(s.text_span || "").slice(0, 600)}</p>
            </li>
          ))}
        </ol>
        <p className="mt-3 text-xs text-slate-500">Company documents approved for reuse only; click a number in the draft to
          highlight its source.</p>
      </Card>
    </div>
  );
}

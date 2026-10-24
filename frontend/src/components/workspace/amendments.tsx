"use client";

import { FilePlus2, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge, Button, Callout, Card, Empty, ErrorBanner, Spinner } from "@/components/ui";
import { usePoll } from "@/hooks/use-poll";
import { api, errorMessage } from "@/lib/api";
import { humanize } from "@/lib/formatting";
import type { AmendmentDiff, AmendmentSummary, TenderView } from "@/lib/types";

const PROCESSING = new Set(["uploaded", "parsed"]);

export function AmendmentPanel({ tender, onChanged, onReanalysed }: {
  tender: TenderView; onChanged: () => void; onReanalysed: (runId: string) => void;
}) {
  const [processing, setProcessing] = useState(false);
  const list = usePoll(() => api.amendments(tender.tenderId), [tender.tenderId, tender.currentVersion],
    { intervalMs: 2000, active: processing });
  const latest: AmendmentSummary | undefined = list.data?.items.at(-1);
  useEffect(() => setProcessing(!!latest && PROCESSING.has(latest.status)), [latest]);
  const diff = usePoll<AmendmentDiff | null>(
    () => (latest && !PROCESSING.has(latest.status) && latest.status !== "failed"
      ? api.amendmentDiff(tender.tenderId, latest.amendment_id) : Promise.resolve(null)),
    [latest?.amendment_id, latest?.status]);
  const [file, setFile] = useState<File | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(name: string, fn: () => Promise<unknown>) {
    setBusy(name);
    setError(null);
    try {
      await fn();
      await list.reload();
      onChanged();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  const canUpload = !latest || latest.status === "confirmed" || latest.status === "failed";
  const changes = diff.data?.changes ?? [];
  const direct = changes.filter((c) => c.kind !== "no_change");

  return (
    <div className="space-y-4">
      <ErrorBanner error={error} />
      <Card title="Add a corrigendum to this tender">
        <p className="mb-3 text-sm text-slate-500">
          The corrigendum becomes version {tender.currentVersion + 1} of the same tender. You review the typed changes
          before anything is applied; the company knowledge base is not touched.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <input type="file" accept=".pdf,.docx" disabled={!canUpload} onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-1.5 file:text-white" />
          <Button disabled={!file || !canUpload} loading={busy === "upload"}
            onClick={() => file && act("upload", () => api.uploadAmendment(tender.tenderId, file))}>
            <FilePlus2 className="size-4" /> Upload corrigendum</Button>
        </div>
      </Card>

      {latest && (
        <Card title={`Corrigendum → v${latest.target_version}`} actions={<Badge status={latest.status} />}>
          {PROCESSING.has(latest.status) && <Spinner label="Reading the amendment tables…" />}
          {latest.status === "failed" && <ErrorBanner error="The corrigendum could not be processed; see the file status." />}
          {diff.data && (
            <div className="space-y-4">
              <h3 className="text-xs font-semibold uppercase text-slate-500">Direct changes published by the buyer ({direct.length})</h3>
              <div className="overflow-x-auto rounded-md border border-slate-200">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                    <tr><th className="px-2 py-2">Item</th><th className="px-2 py-2">Kind</th><th className="px-2 py-2">Field</th>
                      <th className="px-2 py-2">Before</th><th className="px-2 py-2">After</th><th className="px-2 py-2">Re-checks</th></tr>
                  </thead>
                  <tbody>
                    {changes.map((c) => (
                      <tr key={c.change_id} className="border-t border-slate-100 align-top">
                        <td className="whitespace-nowrap px-2 py-2 text-xs">{c.change_id}
                          <div className="text-slate-400">Part {c.part ?? "—"} · p.{c.new_source.page ?? "—"}</div></td>
                        <td className="px-2 py-2"><Badge tone={c.kind === "no_change" ? "slate" : c.kind === "changed" ? "amber" : "blue"}>
                          {humanize(c.kind)}</Badge></td>
                        <td className="px-2 py-2 text-xs">{humanize(c.field)}</td>
                        <td className="clause px-2 py-2 text-xs text-slate-500">{(c.old_value ?? "—").slice(0, 120)}</td>
                        <td className="clause px-2 py-2 text-xs font-medium">{(c.new_value ?? "—").slice(0, 160)}</td>
                        <td className="px-2 py-2 text-xs text-slate-500">{c.downstream_impacts.join(", ") || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div>
                <h3 className="text-xs font-semibold uppercase text-slate-500">Company-specific impact</h3>
                <p className="text-sm text-slate-600">
                  Checks to re-run: {diff.data.invalidated_checks.join(", ") || "none"}. Whether a change hurts this bid
                  (for example a certificate expiring before a new deadline) is decided by re-analysis, not assumed here.
                </p>
              </div>
              {latest.status === "diff_ready" && (
                <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 pt-3">
                  <input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment (audit trail)"
                    className="min-w-64 flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
                  <Button loading={busy === "confirm"} onClick={() => act("confirm", () =>
                    api.confirmAmendment(tender.tenderId, latest.amendment_id, { comment: comment || undefined }))}>
                    <ShieldCheck className="size-4" /> Confirm v{latest.target_version}</Button>
                </div>
              )}
            </div>
          )}
          {latest.status === "confirmed" && tender.status === "reanalysis_required" && (
            <Callout tone="amber" className="mt-4"><div className="flex flex-wrap items-center gap-3">
              v{tender.currentVersion} is effective; the v{tender.currentVersion - 1} Gate 1 decision is superseded.
              <Button className="ml-auto" loading={busy === "reanalyse"} onClick={() => act("reanalyse", async () => {
                const r = await api.reanalyse(tender.tenderId);
                onReanalysed(r.analysis_run_id);
              })}><RefreshCw className="size-4" /> Re-analyse impact</Button>
            </div></Callout>
          )}
        </Card>
      )}
      {!latest && list.data && <Empty>No corrigendum uploaded for this tender.</Empty>}
    </div>
  );
}

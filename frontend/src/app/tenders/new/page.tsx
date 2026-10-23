"use client";

import { Play, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge, Button, Card, ErrorBanner } from "@/components/ui";
import { usePoll } from "@/hooks/use-poll";
import { api, errorMessage } from "@/lib/api";
import type { IngestionStatusResponse } from "@/lib/types";

export default function NewTender() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [buyer, setBuyer] = useState("");
  const [reference, setReference] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [tenderId, setTenderId] = useState<string | null>(null);
  const [rejected, setRejected] = useState<{ filename: string; error: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ingestion = usePoll<IngestionStatusResponse | null>(
    () => (tenderId ? api.ingestion(tenderId) : Promise.resolve(null)), [tenderId],
    { intervalMs: 1500, active: !!tenderId },
  );
  const status = ingestion.data;

  async function createAndUpload() {
    setBusy(true);
    setError(null);
    try {
      const created = await api.createTender({ title, buyer: buyer || undefined, reference_no: reference || undefined });
      setTenderId(created.tenderId);
      const res = await api.uploadFiles(created.tenderId, files);
      setRejected(res.rejected ?? []);
      ingestion.reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function analyze() {
    if (!tenderId) return;
    setBusy(true);
    try {
      await api.run(tenderId);
      router.push(`/tenders/${tenderId}`);
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold">New tender</h1>
        <p className="text-sm text-slate-500">
          Upload the original pack (notice, RFP, annexures, price schedule). A corrigendum is added later, to the
          same tender, from its Documents tab.
        </p>
      </div>
      <ErrorBanner error={error} />
      <Card title="1. Tender details and files">
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm md:col-span-2">Title
            <input value={title} onChange={(e) => setTitle(e.target.value)} disabled={!!tenderId}
              placeholder="Selection of MSP for O&M of the State Data Centre"
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2" />
          </label>
          <label className="text-sm">Buyer
            <input value={buyer} onChange={(e) => setBuyer(e.target.value)} disabled={!!tenderId}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2" />
          </label>
          <label className="text-sm">Reference no.
            <input value={reference} onChange={(e) => setReference(e.target.value)} disabled={!!tenderId}
              className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2" />
          </label>
          <label className="text-sm md:col-span-2">Tender files (PDF, DOCX, XLSX)
            <input type="file" multiple accept=".pdf,.docx,.xlsx,.txt" disabled={!!tenderId}
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
              className="mt-1 block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-slate-900 file:px-3 file:py-1.5 file:text-white" />
          </label>
        </div>
        {!tenderId && (
          <Button className="mt-4" onClick={createAndUpload} loading={busy} disabled={!title.trim() || files.length === 0}>
            <Upload className="size-4" /> Create and upload {files.length > 0 && `(${files.length} files)`}
          </Button>
        )}
      </Card>

      {tenderId && (
        <Card title="2. Validate, parse and index" actions={status && <Badge status={status.ready ? "indexed" : "parsing"}>
          {status.ready ? "Ready for analysis" : "Processing"}</Badge>}>
          {rejected.map((r) => <ErrorBanner key={r.filename} error={`${r.filename}: ${r.error}`} />)}
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-slate-500">
              <tr><th className="py-1">File</th><th>Role</th><th>Status</th><th>Detail</th></tr>
            </thead>
            <tbody>
              {status?.files.map((f) => (
                <tr key={f.doc_id} className="border-t border-slate-100 align-top">
                  <td className="py-2 pr-2 font-medium">{f.filename}</td>
                  <td className="pr-2"><Badge tone="slate" status={f.doc_role} /></td>
                  <td className="pr-2"><Badge status={f.status} /></td>
                  <td className="text-xs text-slate-500">{f.status_detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-4 flex items-center gap-3">
            <Button onClick={analyze} loading={busy} disabled={!status?.ready}>
              <Play className="size-4" /> Analyze
            </Button>
            <span className="text-xs text-slate-500">
              {status?.ready ? "Every file is indexed." : "Analyze unlocks when every file is indexed."}
            </span>
          </div>
        </Card>
      )}
    </div>
  );
}

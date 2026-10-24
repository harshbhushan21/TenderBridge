"use client";

import { AlertTriangle, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { FactsTable, type FactKind } from "@/components/kb/facts";
import { Badge, Button, Card, Empty, ErrorBanner, Spinner, Stat, Tabs } from "@/components/ui";
import { usePoll } from "@/hooks/use-poll";
import { useRole } from "@/hooks/use-role";
import { api, errorMessage } from "@/lib/api";
import { formatDate, humanize } from "@/lib/formatting";
import type { RetrievedChunk } from "@/lib/types";

type Tab = "documents" | FactKind | "search";

export default function KnowledgeBasePage() {
  const role = useRole();
  const [tab, setTab] = useState<Tab>("documents");
  const status = usePoll(() => api.kbStatus(), []);
  const docs = usePoll(() => api.kbDocuments(), [role]);
  const [filter, setFilter] = useState("");
  const [type, setType] = useState("");
  const shown = useMemo(() => (docs.data?.items ?? []).filter((d) =>
    (!type || d.doc_type === type)
    && (!filter || `${d.doc_id} ${d.title ?? ""} ${d.filename}`.toLowerCase().includes(filter.toLowerCase()))),
  [docs.data, filter, type]);

  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<RetrievedChunk[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  async function runSearch() {
    setSearching(true);
    setSearchError(null);
    try {
      setHits((await api.kbSearch(query, 6)).items);
    } catch (e) {
      setSearchError(errorMessage(e));
    } finally {
      setSearching(false);
    }
  }

  const s = status.data;
  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-semibold">Company knowledge base</h1>
        <p className="text-sm text-slate-500">{s?.name ?? "…"}</p>
      </header>
      <ErrorBanner error={status.error} />
      {s && (
        <Card>
          <div className="flex flex-wrap gap-8">
            <Stat label="Status" value={<Badge status={s.status} />} />
            <Stat label="Documents" value={s.documents} hint={`${s.chunks} searchable chunks`} />
            {Object.entries(s.facts).map(([k, v]) => <Stat key={k} label={humanize(k)} value={v} />)}
          </div>
        </Card>
      )}
      {s && s.expiring.length > 0 && (
        <Card title={<span className="flex items-center gap-2"><AlertTriangle className="size-4 text-amber-600" />
          Expired or expiring credentials</span>}>
          <ul className="grid gap-2 text-sm md:grid-cols-2">
            {s.expiring.map((e, i) => (
              <li key={`${e.kind}-${e.id ?? ""}-${e.name}-${i}`} className="flex items-center justify-between gap-3 rounded-md border border-slate-200 px-3 py-2">
                <div><div className="font-medium">{e.name}</div>
                  <div className="text-xs text-slate-500">{humanize(e.kind)}{e.id ? ` · ${e.id}` : ""}{e.source ? ` · ${e.source}` : ""}</div></div>
                <Badge tone={e.days_left < 0 ? "red" : e.days_left <= 60 ? "amber" : "slate"}>
                  {e.days_left < 0 ? `expired ${formatDate(e.expiry_date)}` : `${e.days_left} days left`}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Tabs<Tab> value={tab} onChange={setTab} tabs={[
        { id: "documents", label: `Documents${docs.data ? ` (${docs.data.items.length})` : ""}` },
        { id: "financials", label: "Financials" }, { id: "certificates", label: "Certificates" },
        { id: "projects", label: "Projects" }, { id: "people", label: "People" },
        { id: "risk_positions", label: "Risk positions" }, { id: "search", label: "Search" },
      ]} />

      {tab === "documents" && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by id or title"
              className="min-w-56 flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
            <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Document type"
              className="rounded-md border border-slate-300 bg-white px-2 py-1.5 text-sm">
              <option value="">All types</option>
              {Object.keys(s?.by_type ?? {}).sort().map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
            </select>
          </div>
          <p className="text-xs text-slate-500">Showing documents your role may read ({role === "analyst" ? "Analyst" : "Bid Manager"});
            restricted ones are filtered by the API before retrieval.</p>
          {docs.loading && !docs.data ? <Spinner /> : (
            <div className="overflow-x-auto rounded-md border border-slate-200">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
                  <tr><th className="px-3 py-2">Document</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Pages</th>
                    <th className="px-3 py-2">Sensitivity</th><th className="px-3 py-2">Reuse</th><th className="px-3 py-2">Index</th></tr>
                </thead>
                <tbody>
                  {shown.map((d) => (
                    <tr key={d.doc_id} className="border-t border-slate-100">
                      <td className="px-3 py-2"><div className="font-medium">{d.title || d.filename}</div>
                        <div className="text-xs text-slate-500">{d.doc_id} · {d.filename}</div></td>
                      <td className="px-3 py-2 text-xs">{humanize(d.doc_type)}</td>
                      <td className="px-3 py-2">{d.page_count ?? "—"}</td>
                      <td className="px-3 py-2"><Badge tone={d.sensitivity === "internal" ? "slate" : "amber"}>{d.sensitivity}</Badge></td>
                      <td className="px-3 py-2">{d.approved_for_reuse ? <Badge tone="green">approved</Badge> : <Badge tone="red">not approved</Badge>}</td>
                      <td className="px-3 py-2"><Badge status={d.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
      {(["financials", "certificates", "projects", "people", "risk_positions"] as const).map((k) =>
        tab === k ? <FactsTable key={k} kind={k} role={role} /> : null)}
      {tab === "search" && (
        <div className="space-y-3">
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (query.trim().length >= 2) void runSearch(); }}>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. ISO 27001 validity, similar work in banking"
              className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
            <Button type="submit" loading={searching} disabled={query.trim().length < 2}><Search className="size-4" /> Search</Button>
          </form>
          <p className="text-xs text-slate-500">Hybrid search (keywords + embeddings), filtered by your role before ranking.</p>
          <ErrorBanner error={searchError} />
          {hits?.length === 0 && <Empty>No visible passages match.</Empty>}
          <ul className="space-y-2">
            {hits?.map((h) => (
              <li key={h.chunk_id} className="rounded-md border border-slate-200 bg-white p-3 text-sm">
                <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <span className="font-medium text-slate-700">{h.doc_id}</span>{h.page ? <span>p.{h.page}</span> : null}
                  {h.section_path && <span>· {h.section_path}</span>}
                  <span className="ml-auto">score {h.score.toFixed(3)}</span>
                </div>
                <p className="clause text-slate-700">{h.text.slice(0, 500)}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

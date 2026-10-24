"use client";

import { Badge, Callout, ErrorBanner, Spinner } from "@/components/ui";
import { usePoll } from "@/hooks/use-poll";
import { api } from "@/lib/api";
import { formatDate, formatInrCrore, humanize } from "@/lib/formatting";

export type FactKind = "financials" | "certificates" | "projects" | "people" | "risk_positions";
type Row = Record<string, unknown>;

const str = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));
const source = (r: Row) => {
  const s = r.source as { doc_id?: string; page?: number } | undefined;
  return s?.doc_id ? `${s.doc_id}${s.page ? ` p.${s.page}` : ""}` : "—";
};

/** Column definitions per fact kind: the structured facts the hard-gate rules read. */
const COLUMNS: Record<FactKind, { label: string; cell: (r: Row) => React.ReactNode }[]> = {
  financials: [
    { label: "Year", cell: (r) => str(r.fiscal_year) },
    { label: "Revenue", cell: (r) => formatInrCrore(r.revenue_inr as number) },
    { label: "Net worth", cell: (r) => formatInrCrore(r.net_worth_inr as number) },
    { label: "PAT", cell: (r) => formatInrCrore(r.profit_after_tax_inr as number) },
    { label: "Audited / CA", cell: (r) => `${r.audited ? "yes" : "no"} / ${r.ca_certified ? "yes" : "no"}` },
    { label: "Source", cell: source },
  ],
  certificates: [
    { label: "Certificate", cell: (r) => <span className="font-medium">{str(r.name)}</span> },
    { label: "Number", cell: (r) => str(r.certificate_no) },
    { label: "Valid until", cell: (r) => formatDate(r.expiry_date as string) },
    { label: "Status", cell: (r) => <Badge status={String(r.status)}>{humanize(String(r.status))}</Badge> },
    { label: "Scope", cell: (r) => <span className="clause text-xs text-slate-600">{str(r.scope).slice(0, 140)}</span> },
    { label: "Source", cell: source },
  ],
  projects: [
    { label: "Project", cell: (r) => <><div className="font-medium">{str(r.name)}</div>
      <div className="text-xs text-slate-500">{str(r.project_id)} · {str(r.client)}</div></> },
    { label: "Value", cell: (r) => formatInrCrore(r.contract_value_inr as number) },
    { label: "Period", cell: (r) => `${formatDate(r.start_date as string)} – ${formatDate(r.completion_date as string)}` },
    { label: "Status", cell: (r) => <Badge status={String(r.status)}>{humanize(String(r.status))}</Badge> },
    { label: "Completion cert.", cell: (r) => (r.completion_certificate ? "yes" : "no") },
  ],
  people: [
    { label: "Person", cell: (r) => <><div className="font-medium">{str(r.name)}</div>
      <div className="text-xs text-slate-500">{str(r.role)}</div></> },
    { label: "Experience", cell: (r) => `${str(r.years_experience)} yrs` },
    { label: "Certifications", cell: (r) => (
      <div className="flex flex-wrap gap-1">
        {((r.certifications as { name: string; valid?: boolean; expiry_date?: string | null }[]) || []).map((c) => (
          <Badge key={c.name} tone={c.valid === false ? "red" : "slate"}>
            {c.name}{c.expiry_date ? ` · ${formatDate(c.expiry_date)}` : ""}</Badge>
        ))}
      </div>) },
    { label: "Available from", cell: (r) => (r.available ? formatDate(r.available_from as string) : "not available") },
  ],
  risk_positions: [
    { label: "Clause", cell: (r) => <span className="font-medium">{humanize(String(r.category))}</span> },
    { label: "Approved position", cell: (r) => <span className="text-xs text-slate-600">{str(r.policy)}</span> },
    { label: "Approver", cell: (r) => str(r.approver) },
  ],
};

export function FactsTable({ kind, role }: { kind: FactKind; role: string }) {
  const facts = usePoll(() => api.kbFacts(kind), [kind, role]);
  if (facts.loading && !facts.data) return <Spinner />;
  if (facts.error) {
    return kind === "risk_positions"
      ? <Callout tone="amber">Approved commercial risk positions are visible to
        bid managers only. The refusal is enforced by the API, not just hidden here.</Callout>
      : <ErrorBanner error={facts.error} />;
  }
  const cols = COLUMNS[kind];
  return (
    <div className="space-y-2">
      {kind === "people" && (
        <p className="text-xs text-slate-500">Personal names are masked at ingestion and stored as employee IDs; they are
          never sent to a model or a trace.</p>
      )}
      <div className="overflow-x-auto rounded-md border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr>{cols.map((c) => <th key={c.label} className="px-3 py-2">{c.label}</th>)}</tr>
          </thead>
          <tbody>
            {facts.data?.items.map((row, i) => (
              <tr key={i} className="border-t border-slate-100 align-top">
                {cols.map((c) => <td key={c.label} className="px-3 py-2">{c.cell(row)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

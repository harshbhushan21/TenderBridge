"use client";

import { BookOpen, X } from "lucide-react";
import { useState } from "react";

import { Badge, Button, ErrorBanner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { humanize, spanLabel } from "@/lib/formatting";
import type { ComplianceItem, Requirement, SourceSpan } from "@/lib/types";

function value(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v, null, 1);
}

/** Side panel: the tender clause, the company evidence and the rule trace behind one verdict. */
export function EvidencePanel({ tenderId, item, requirement, fileNames, onClose }: {
  tenderId: string; item: ComplianceItem; requirement?: Requirement;
  fileNames: Record<string, string>; onClose: () => void;
}) {
  const [page, setPage] = useState<{ label: string; text: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const src = item.tender_source;
  const name = (s: SourceSpan) => fileNames[s.doc_id] ?? s.doc_id;

  async function showPage(s: SourceSpan) {
    if (!s.page) return;
    try {
      const p = await api.pageText(tenderId, s.doc_id, s.page);
      setPage({ label: `${name(s)} · page ${s.page}`, text: p.text });
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <aside className="fixed inset-y-0 right-0 z-20 flex w-full max-w-xl flex-col border-l border-slate-200 bg-white shadow-xl">
      <header className="flex items-start justify-between gap-3 border-b border-slate-100 p-4">
        <div>
          <div className="text-xs text-slate-500">{item.requirement_id} · {humanize(item.category)}
            {item.hard_gate && " · hard gate"}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Badge status={item.status} />
            {item.reused_from_version && <Badge tone="slate">reused from v{item.reused_from_version}</Badge>}
            <Badge tone="slate">checked by {item.checked_by}</Badge>
          </div>
        </div>
        <Button variant="ghost" onClick={onClose} aria-label="Close"><X className="size-4" /></Button>
      </header>
      <div className="flex-1 space-y-5 overflow-y-auto p-4 text-sm">
        <ErrorBanner error={error} />
        <section>
          <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Verdict</h3>
          <p>{item.summary}</p>
          {item.actions.length > 0 && (
            <ul className="mt-2 list-disc pl-5 text-amber-800">{item.actions.map((a) => <li key={a}>{a}</li>)}</ul>
          )}
        </section>
        <section>
          <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Tender clause</h3>
          <blockquote className="clause rounded-md bg-slate-50 p-3 text-slate-800">
            {requirement?.text ?? src.text_span}
          </blockquote>
          <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
            {name(src)}{src.page ? ` · page ${src.page}` : ""}{src.section_path ? ` · ${src.section_path}` : ""}
            {src.page && <button className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-sky-700 hover:underline"
              onClick={() => showPage(src)}><BookOpen className="size-3.5" /> show page</button>}
          </div>
        </section>
        {item.rule_result && item.rule_result.calculations.length > 0 && (
          <section>
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Rule trace</h3>
            <dl className="divide-y divide-slate-100 rounded-md border border-slate-200">
              {item.rule_result.calculations.map((c, i) => (
                <div key={i} className="grid grid-cols-3 gap-2 px-3 py-2">
                  <dt className="text-slate-500">{c.label}</dt>
                  <dd className="clause col-span-2 whitespace-pre-wrap font-mono text-xs">{value(c.value)}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}
        <section>
          <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">Company evidence</h3>
          {item.company_evidence.length === 0 ? <p className="text-slate-500">No company document cited.</p> : (
            <ul className="space-y-2">
              {item.company_evidence.map((e, i) => (
                <li key={i} className="rounded-md border border-slate-200 p-2">
                  <div className="text-xs text-slate-500">{spanLabel(e)}</div>
                  {e.text_span && <div className="clause mt-1">{e.text_span}</div>}
                </li>
              ))}
            </ul>
          )}
        </section>
        {page && (
          <section>
            <h3 className="mb-1 text-xs font-semibold uppercase text-slate-500">{page.label}</h3>
            <pre className="clause max-h-96 overflow-y-auto whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-xs">{page.text}</pre>
          </section>
        )}
      </div>
    </aside>
  );
}

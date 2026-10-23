"use client";

import { useMemo, useState } from "react";

import { Badge, Empty } from "@/components/ui";
import { humanize } from "@/lib/formatting";
import type { ComplianceItem, Requirement } from "@/lib/types";

const FILTERS = ["hard_gates", "all", "needs_human"] as const;

export function RequirementsMatrix({ items, requirements, onOpen }: {
  items: ComplianceItem[]; requirements: Record<string, Requirement>; onOpen: (item: ComplianceItem) => void;
}) {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("hard_gates");
  const [q, setQ] = useState("");
  const rows = useMemo(() => items.filter((c) =>
    (filter === "all" || (filter === "hard_gates" ? c.hard_gate : c.status === "needs_human")) &&
    (!q || `${c.requirement_id} ${requirements[c.requirement_id]?.text ?? ""}`.toLowerCase().includes(q.toLowerCase())),
  ), [items, requirements, filter, q]);

  if (items.length === 0) return <Empty>No requirements yet: run the analysis.</Empty>;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button key={f} onClick={() => setFilter(f)}
            className={`rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${filter === f ?
              "bg-slate-900 text-white ring-slate-900" : "bg-white text-slate-600 ring-slate-300"}`}>
            {f === "hard_gates" ? `Hard gates (${items.filter((c) => c.hard_gate).length})` :
              f === "all" ? `All (${items.length})` : `Unchecked (${items.filter((c) => c.status === "needs_human").length})`}
          </button>
        ))}
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search requirements"
          className="ml-auto w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm" />
      </div>
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
            <tr><th className="px-3 py-2">ID</th><th className="px-3 py-2">Requirement</th><th className="px-3 py-2">Category</th>
              <th className="px-3 py-2">Page</th><th className="px-3 py-2">Status</th></tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.requirement_id} onClick={() => onOpen(c)}
                className="cursor-pointer border-t border-slate-100 align-top hover:bg-slate-50">
                <td className="whitespace-nowrap px-3 py-2 text-xs font-medium text-slate-500">{c.requirement_id}</td>
                <td className="clause px-3 py-2">{(requirements[c.requirement_id]?.text ?? c.summary).slice(0, 220)}</td>
                <td className="whitespace-nowrap px-3 py-2 text-xs">{humanize(c.category)}</td>
                <td className="px-3 py-2 text-xs">{c.tender_source.page ?? "—"}</td>
                <td className="px-3 py-2"><Badge status={c.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

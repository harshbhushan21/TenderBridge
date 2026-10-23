"use client";

import { Badge, Empty } from "@/components/ui";
import { humanize } from "@/lib/formatting";
import type { RiskItem } from "@/lib/types";

export function RisksTable({ risks }: { risks: RiskItem[] }) {
  if (risks.length === 0) return <Empty>No contract risks yet: run the analysis.</Empty>;
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
          <tr><th className="px-3 py-2">Clause</th><th className="px-3 py-2">Tender says</th>
            <th className="px-3 py-2">Company position</th><th className="px-3 py-2">Verdict</th><th className="px-3 py-2">Approver</th></tr>
        </thead>
        <tbody>
          {risks.map((r) => (
            <tr key={r.risk_id} className="border-t border-slate-100 align-top">
              <td className="whitespace-nowrap px-3 py-2 font-medium">{humanize(r.category)}</td>
              <td className="clause px-3 py-2">{r.tender_value}
                {r.source?.page && <div className="text-xs text-slate-400">page {r.source.page}</div>}</td>
              <td className="clause px-3 py-2 text-slate-600">{r.policy_value}</td>
              <td className="px-3 py-2"><Badge status={r.level} /></td>
              <td className="px-3 py-2 text-xs text-slate-600">{r.approver ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

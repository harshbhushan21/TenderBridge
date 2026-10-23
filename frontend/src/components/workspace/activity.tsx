"use client";

import { Badge, Card, ErrorBanner } from "@/components/ui";
import { usePoll } from "@/hooks/use-poll";
import { api } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/formatting";

export function ActivityTab({ tenderId }: { tenderId: string }) {
  const audit = usePoll(() => api.audit(tenderId), [tenderId], { intervalMs: 5000 });
  const guards = usePoll(() => api.opsGuardrails(tenderId), [tenderId]);
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="Audit trail" className="lg:col-span-2">
        <ErrorBanner error={audit.error} />
        <ol className="divide-y divide-slate-100 text-sm">
          {audit.data?.items.map((e, i) => (
            <li key={i} className="flex flex-wrap items-baseline gap-x-3 py-2">
              <span className="w-40 shrink-0 text-xs text-slate-500">{formatDateTime(e.ts)}</span>
              <span className="font-medium">{e.action}</span>
              <span className="text-slate-600">{e.actor}</span>
              {e.version != null && <Badge tone="slate">v{e.version}</Badge>}
            </li>
          ))}
        </ol>
      </Card>
      <Card title="Guardrail events">
        {guards.data?.items.length === 0 && <p className="text-sm text-slate-500">None for this tender.</p>}
        <ul className="space-y-2 text-sm">
          {guards.data?.items.map((g, i) => (
            <li key={i} className="rounded-md border border-slate-200 p-2">
              <div className="flex items-center gap-2"><Badge status={g.severity} />{humanize(g.kind)}
                {g.quarantined && <Badge tone="red">quarantined</Badge>}</div>
              <p className="clause mt-1 text-xs text-slate-600">{(g.excerpt ?? "").slice(0, 200)}</p>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

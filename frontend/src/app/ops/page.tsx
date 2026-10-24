"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge, Card, Empty, ErrorBanner, Spinner, Stat } from "@/components/ui";
import { usePoll } from "@/hooks/use-poll";
import { api } from "@/lib/api";
import { formatDateTime, humanize } from "@/lib/formatting";
import type { EvalReport, RequirementScore } from "@/lib/types";

const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
const LANGSMITH_URL = process.env.NEXT_PUBLIC_LANGSMITH_URL || "https://smith.langchain.com";

export default function AgentOpsPage() {
  const summary = usePoll(() => api.opsSummary(), [], { intervalMs: 10000 });
  const evals = usePoll(() => api.opsEvals(), []);
  const runs = usePoll(() => api.opsRuns(), [], { intervalMs: 10000 });
  const guards = usePoll(() => api.opsGuardrails(), [], { intervalMs: 10000 });
  const settings = usePoll(() => api.settings(), []);
  const [selected, setSelected] = useState<string | null>(null);
  const metrics = usePoll(() => (selected ? api.opsMetrics(selected) : Promise.resolve(null)), [selected]);

  const s = summary.data;
  const tracing = settings.data?.langsmith;
  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">AgentOps</h1>
          <p className="text-sm text-slate-500">Cost, latency, evaluations and guardrail events per run.</p>
        </div>
        {tracing?.tracing ? (
          <a href={LANGSMITH_URL} target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-1 text-sm font-medium text-sky-700 hover:underline">
            LangSmith traces · {tracing.project} <ExternalLink className="size-3.5" /></a>
        ) : (
          <span className="text-xs text-slate-500">LangSmith tracing is off (set LANGSMITH_TRACING=true and a key in .env)</span>
        )}
      </header>
      <ErrorBanner error={summary.error} />

      {s && (
        <Card>
          <div className="flex flex-wrap gap-8">
            <Stat label="Runs" value={s.runs.total}
              hint={Object.entries(s.runs.by_status).map(([k, v]) => `${v} ${humanize(k)}`).join(", ") || "none yet"} />
            <Stat label="Analysis time" value={s.analysis_seconds.avg == null ? "—" : `${s.analysis_seconds.avg}s avg`}
              hint={s.analysis_seconds.max == null ? undefined : `max ${s.analysis_seconds.max}s, to Gate 1`} />
            <Stat label="LLM calls" value={s.llm.calls}
              hint={`${s.llm.input_tokens + s.llm.output_tokens} tokens${s.llm.cached_calls ? `, ${s.llm.cached_calls} from cache` : ""}`} />
            <Stat label="LLM cost" value={`$${s.llm.cost_usd.toFixed(4)}`}
              hint={s.llm.unpriced_calls ? `${s.llm.unpriced_calls} calls have no configured price` : "priced calls only"} />
            <Stat label="Guardrail events" value={s.guardrails.total} hint={`${s.guardrails.quarantined} quarantined`} />
          </div>
          {Object.keys(s.llm.by_model).length > 0 && (
            <table className="mt-4 w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500">
                <tr><th className="py-1">Model</th><th>Calls (cached)</th><th>Tokens in / out</th><th>Avg latency</th><th>Errors</th><th>Cost</th></tr>
              </thead>
              <tbody>
                {Object.entries(s.llm.by_model).map(([model, m]) => (
                  <tr key={model} className="border-t border-slate-100">
                    <td className="py-1 font-medium">{model}</td><td>{m.calls}{m.cached ? ` (${m.cached})` : ""}</td>
                    <td>{m.input_tokens} / {m.output_tokens}</td><td>{m.avg_latency_ms} ms</td><td>{m.errors}</td>
                    <td>${m.cost_usd.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}

      <EvalCard report={evals.data} loading={evals.loading} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Analysis runs">
          {runs.loading && !runs.data && <Spinner />}
          {runs.data?.items.length === 0 && <Empty>No runs yet.</Empty>}
          <ul className="divide-y divide-slate-100 text-sm">
            {runs.data?.items.slice(0, 25).map((r) => (
              <li key={r.run_id}>
                <button onClick={() => setSelected(r.run_id)}
                  className={`flex w-full flex-wrap items-center gap-2 px-1 py-2 text-left hover:bg-slate-50 ${selected === r.run_id ? "bg-slate-50" : ""}`}>
                  <span className="font-medium">{r.run_id}</span>
                  <Badge status={r.status} />
                  <span className="text-xs text-slate-500">{r.tender_id} v{r.version} · {humanize(r.mode)}</span>
                  <span className="ml-auto text-xs text-slate-500">{formatDateTime(r.started_at)}</span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <Card title={selected ? `Node latency · ${selected}` : "Node latency"}>
          {!selected && <p className="text-sm text-slate-500">Select a run to see where its time went.</p>}
          {metrics.data && (
            <div className="space-y-2 text-sm">
              {(() => {
                const entries = Object.entries(metrics.data.latency_ms_by_node ?? {});
                const max = Math.max(1, ...entries.map(([, v]) => v));
                return entries.length === 0 ? <p className="text-slate-500">No node events recorded for this run.</p>
                  : entries.map(([node, ms]) => (
                    <div key={node}>
                      <div className="flex justify-between text-xs"><span>{humanize(node)}</span><span>{ms.toFixed(0)} ms</span></div>
                      <div className="h-1.5 rounded bg-slate-100"><div className="h-1.5 rounded bg-olive" style={{ width: `${(ms / max) * 100}%` }} /></div>
                    </div>
                  ));
              })()}
              <p className="pt-2 text-xs text-slate-500">LLM calls: {metrics.data.llm.calls} · cost ${metrics.data.llm.cost_usd.toFixed(4)}</p>
              {metrics.data.run_id && (
                <Link className="text-xs text-sky-700 hover:underline"
                  href={`/tenders/${runs.data?.items.find((r) => r.run_id === selected)?.tender_id ?? ""}`}>Open tender</Link>
              )}
            </div>
          )}
        </Card>
      </div>

      <Card title="Guardrail events">
        {guards.data?.items.length === 0 && (
          <p className="text-sm text-slate-500">None recorded. Uploading <code>demo_data/evaluation/safety_traps/injection_test.pdf</code> to a
            tender shows hidden-text, visible-instruction and metadata injections being quarantined.</p>
        )}
        <ul className="space-y-2 text-sm">
          {guards.data?.items.slice(0, 50).map((g, i) => (
            <li key={g.id ?? i} className="rounded-md border border-slate-200 p-2">
              <div className="flex flex-wrap items-center gap-2"><Badge status={g.severity} />{humanize(g.kind)}
                {g.quarantined && <Badge tone="red">quarantined</Badge>}
                <span className="text-xs text-slate-500">{g.doc_id}{g.page ? ` p.${g.page}` : ""}{g.tender_id ? ` · ${g.tender_id}` : ""}</span>
                <span className="ml-auto text-xs text-slate-500">{formatDateTime(g.ts)}</span></div>
              <p className="clause mt-1 text-xs text-slate-600">{(g.excerpt ?? "").slice(0, 240)}</p>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function ScoreRow({ label, v }: { label: string; v?: RequirementScore }) {
  if (!v) return null;
  return (
    <tr className="border-t border-slate-100">
      <td className="py-1">{label}</td>
      <td>{v.mandatory_found}/{v.mandatory_expected} ({pct(v.mandatory_recall)})</td>
      <td>{pct(v.recall_all)}</td><td>{pct(v.precision)}</td><td>{pct(v.mandatory_flag_accuracy)}</td>
    </tr>
  );
}

function EvalCard({ report, loading }: { report: EvalReport | null; loading: boolean }) {
  if (loading && !report) return <Card title="Evaluation"><Spinner /></Card>;
  const r = report?.results;
  if (!report?.available || !r) {
    return (
      <Card title="Evaluation">
        <p className="text-sm text-slate-500">No evaluation report yet. Run <code>uv run python dev.py evals</code>: it analyses
          TDR-001 on a fresh database and scores it against the gold files.</p>
      </Card>
    );
  }
  return (
    <Card title="Evaluation against the gold files" actions={
      <span className="text-xs text-slate-500">{formatDateTime(report.generated_at)} · {r.cost.llm_fast} / {r.retrieval.embedder}</span>}>
      <div className="grid gap-6 lg:grid-cols-2">
        <div>
          <h3 className="text-xs font-semibold uppercase text-slate-500">Requirement extraction</h3>
          <table className="mt-1 w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr><th className="py-1">Scope</th><th>Mandatory recall</th><th>All recall</th><th>Precision</th><th>Flag acc.</th></tr>
            </thead>
            <tbody>
              <ScoreRow label="v1 · all gold" v={r.requirements.v1?.all_gold} />
              <ScoreRow label="v2 · all gold" v={r.requirements.v2?.all_gold} />
              <ScoreRow label="v1 · live subset" v={r.requirements.v1?.live_subset} />
              <ScoreRow label="v2 · live subset" v={r.requirements.v2?.live_subset} />
            </tbody>
          </table>
          <h3 className="mt-4 text-xs font-semibold uppercase text-slate-500">Bid assessment</h3>
          <ul className="mt-1 space-y-1 text-sm">
            {Object.entries(r.assessment).map(([k, a]) => (
              <li key={k} className="flex items-center gap-2">{a.match ? <Badge tone="green">match</Badge> : <Badge tone="red">differs</Badge>}
                <span className="whitespace-nowrap font-medium">{k}</span>
                <span className="text-slate-600">got {a.got ? `${a.got[0]} ${humanize(a.got[1])}` : "—"} · expected {a.expected[0]} {humanize(a.expected[1])}</span></li>
            ))}
          </ul>
        </div>
        <div className="space-y-4 text-sm">
          <div>
            <h3 className="text-xs font-semibold uppercase text-slate-500">Retrieval (recall@6 / MRR)</h3>
            <p>Tender {pct(r.retrieval.tender.recall_at_6)} / {r.retrieval.tender.mrr.toFixed(2)} ·
              Company {pct(r.retrieval.company.recall_at_6)} / {r.retrieval.company.mrr.toFixed(2)}</p>
          </div>
          <div>
            <h3 className="text-xs font-semibold uppercase text-slate-500">Safety</h3>
            <p>Injection traps caught: <span className="font-medium">{r.safety.injection_traps_caught}</span></p>
            <p>Bad draft claims struck: <span className="font-medium">{r.claims.bad_claims_struck}</span>
              {r.claims.good_claims_wrongly_struck.length > 0 &&
                <span className="text-slate-500"> · {r.claims.good_claims_wrongly_struck.length} good claims also struck ({r.claims.mode})</span>}</p>
          </div>
          <div>
            <h3 className="text-xs font-semibold uppercase text-slate-500">Time and cost (one tender, v1 + corrigendum)</h3>
            <p>{Object.entries(r.timings).filter(([k]) => k !== "total_s").map(([k, v]) => `${humanize(k.replace(/_s$/, ""))} ${v}s`).join(" · ")}</p>
            <p>Total {r.timings.total_s}s · {r.cost.llm_calls} LLM calls · ${r.cost.cost_usd.toFixed(4)}</p>
          </div>
        </div>
      </div>
    </Card>
  );
}

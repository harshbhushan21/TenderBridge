"use client";

import { Check, CircleDashed, Loader2, PauseCircle, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { subscribeRunEvents, type ConnectionState } from "@/lib/events";
import { cn } from "@/lib/formatting";
import { NODE_LABELS, NODE_ORDER, type RunEvent } from "@/lib/types";

type NodeState = "pending" | "running" | "done" | "failed" | "waiting";

/** Live graph progress from real run events (SSE with polling fallback). */
export function NodeStrip({ tenderId, runId, onFinished, nodes = NODE_ORDER, labels = NODE_LABELS }: {
  tenderId: string; runId: string; onFinished?: (event: RunEvent) => void;
  nodes?: readonly string[]; labels?: Record<string, string>;
}) {
  const [states, setStates] = useState<Record<string, NodeState>>({});
  const [conn, setConn] = useState<ConnectionState>("connecting");

  useEffect(() => {
    setStates({});
    return subscribeRunEvents({
      tenderId, runId, onState: setConn,
      onEvent: (e) => {
        if (e.node) {
          const next: NodeState | undefined = {
            node_started: "running", node_completed: "done", node_failed: "failed",
            human_review_required: "waiting",
          }[e.event as string] as NodeState | undefined;
          if (next) setStates((s) => ({ ...s, [e.node as string]: next }));
        }
        if (e.event === "run_completed" || e.event === "run_failed") onFinished?.(e);
      },
    });
    // onFinished is a callback prop; re-subscribing on every render would replay events
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenderId, runId]);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
        <span>Run {runId}</span>
        <span>{conn === "open" ? "live" : conn}</span>
      </div>
      <ol className="flex flex-wrap gap-2">
        {nodes.map((node) => {
          const s = states[node] ?? "pending";
          const Icon = { pending: CircleDashed, running: Loader2, done: Check, failed: XCircle, waiting: PauseCircle }[s];
          return (
            <li key={node} className={cn("flex items-center gap-1.5 rounded-md px-2 py-1 text-xs ring-1 ring-inset",
              s === "done" && "bg-emerald-50 text-emerald-800 ring-emerald-200",
              s === "running" && "bg-sky-50 text-sky-800 ring-sky-200",
              s === "waiting" && "bg-violet-50 text-violet-800 ring-violet-200",
              s === "failed" && "bg-red-50 text-red-800 ring-red-200",
              s === "pending" && "bg-slate-50 text-slate-500 ring-slate-200")}>
              <Icon className={cn("size-3.5", s === "running" && "animate-spin")} /> {labels[node] ?? node}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

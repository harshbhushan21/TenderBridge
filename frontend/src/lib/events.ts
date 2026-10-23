// EventSource wrapper with reconnect and JSON polling fallback.
// SSE cannot send custom headers; the API treats identity headers as optional for reads.
import { api } from "./api";
import type { RunEvent, RunEventName } from "./types";

const EVENT_NAMES: RunEventName[] = [
  "run_started", "node_started", "node_completed", "node_failed", "human_review_required",
  "run_completed", "run_failed", "amendment_diff_ready", "budget_exceeded", "file_status",
];

export type ConnectionState = "connecting" | "open" | "polling" | "closed";

export interface RunStreamOptions {
  tenderId: string;
  runId?: string;
  onEvent: (e: RunEvent) => void;
  onState?: (s: ConnectionState) => void;
  pollIntervalMs?: number;
}

function normalise(list: unknown): RunEvent[] {
  if (Array.isArray(list)) return list as RunEvent[];
  if (list && typeof list === "object" && Array.isArray((list as { items?: unknown }).items)) {
    return (list as { items: RunEvent[] }).items;
  }
  return [];
}

/** Subscribe to run events. Returns an unsubscribe function. */
export function subscribeRunEvents(opts: RunStreamOptions): () => void {
  const { tenderId, runId, onEvent, onState } = opts;
  const pollMs = opts.pollIntervalMs ?? 2500;
  let lastId = 0;
  let closed = false;
  let es: EventSource | null = null;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let failures = 0;
  const seen = new Set<number>();

  const deliver = (e: RunEvent) => {
    if (typeof e.id === "number") {
      if (seen.has(e.id)) return;
      seen.add(e.id);
      lastId = Math.max(lastId, e.id);
    }
    onEvent(e);
  };

  const poll = async () => {
    if (closed || !runId) return;
    try {
      const res = await api.eventsJson(tenderId, runId, lastId);
      normalise(res).forEach(deliver);
    } catch {
      /* keep polling */
    }
    if (!closed) pollTimer = setTimeout(poll, pollMs);
  };

  const startPolling = () => {
    if (pollTimer || closed) return;
    onState?.("polling");
    poll();
  };

  const connect = () => {
    if (closed) return;
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      startPolling();
      return;
    }
    onState?.("connecting");
    es = new EventSource(api.eventsUrl(tenderId, runId, lastId));
    const handler = (msg: MessageEvent) => {
      try {
        const data = JSON.parse(msg.data) as RunEvent;
        if (!data.event) data.event = msg.type as RunEventName;
        deliver(data);
      } catch {
        /* ignore malformed */
      }
    };
    es.onopen = () => {
      failures = 0;
      if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
      }
      onState?.("open");
    };
    es.onmessage = handler;
    EVENT_NAMES.forEach((n) => es?.addEventListener(n, handler as EventListener));
    es.onerror = () => {
      es?.close();
      es = null;
      failures += 1;
      // catch up through the persisted JSON log, then retry SSE with backoff
      startPolling();
      const delay = Math.min(30000, 1000 * 2 ** failures);
      retryTimer = setTimeout(() => {
        if (pollTimer) {
          clearTimeout(pollTimer);
          pollTimer = null;
        }
        connect();
      }, delay);
    };
  };

  connect();

  return () => {
    closed = true;
    es?.close();
    if (pollTimer) clearTimeout(pollTimer);
    if (retryTimer) clearTimeout(retryTimer);
    onState?.("closed");
  };
}

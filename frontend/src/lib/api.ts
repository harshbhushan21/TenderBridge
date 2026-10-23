// Typed fetch client for the TenderBridge API (docs/api_contract.md).
import type {
  AmendmentDiff, AmendmentSummary, AuditEntry, BidAssessment, CompareResponse, ComplianceItem,
  DraftReview, ExportInfo, GateDecision, GuardrailEvent, IngestionStatusResponse, Items, KbDocument,
  KbStatus, KeyFacts, OpsMetrics, PageText, ReadyResponse, Requirement, RetrievedChunk, RiskItem,
  RunEvent, RunInfo, SectionDraft, SettingsResponse, SourceSpan, TenderView, VersionsResponse,
} from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000").replace(/\/$/, "");
const DEMO_USER = process.env.NEXT_PUBLIC_DEMO_USER || "bid.manager@nimbus.example";
const DEMO_ROLE = process.env.NEXT_PUBLIC_DEMO_ROLE || "bid_manager";

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function currentUser(): string {
  if (typeof window !== "undefined") {
    try {
      return window.localStorage.getItem("tb.user") || DEMO_USER;
    } catch {
      return DEMO_USER;
    }
  }
  return DEMO_USER;
}

function headers(extra?: HeadersInit): Headers {
  const h = new Headers(extra);
  h.set("X-User", currentUser());
  h.set("X-Role", DEMO_ROLE);
  return h;
}

async function parseError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON */
  }
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.error === "string") {
      return new ApiError(res.status, b.error, String(b.message ?? b.error), (b.details as Record<string, unknown>) ?? {});
    }
    if (b.detail !== undefined) {
      const msg = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
      return new ApiError(res.status, "http_error", msg);
    }
  }
  return new ApiError(res.status, "http_error", `${res.status} ${res.statusText}`);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers: headers(init.headers), cache: "no-store" });
  } catch (e) {
    throw new ApiError(0, "network_error", `Cannot reach API at ${API_BASE} (${(e as Error).message})`);
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function json<T>(path: string, method: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

const t = (id: string) => `/tenders/${encodeURIComponent(id)}`;

export const api = {
  // health / settings
  health: () => request<{ status: string }>("/health"),
  ready: () => request<ReadyResponse>("/ready"),
  settings: () => request<SettingsResponse>("/settings"),

  // knowledge base
  kbStatus: () => request<KbStatus>("/kb/status"),
  kbDocuments: (params: { doc_type?: string; q?: string } = {}) =>
    request<Items<KbDocument>>(`/kb/documents${qs(params)}`),
  kbFacts: (kind: string) => request<Items<Record<string, unknown>>>(`/kb/facts/${kind}`),
  kbSearch: (q: string, k = 6) => request<Items<RetrievedChunk>>(`/kb/search${qs({ q, k })}`),
  kbIngest: (force = false) => json<{ job: string }>("/kb/ingest", "POST", { force }),

  // tenders
  listTenders: () => request<Items<TenderView>>("/tenders"),
  getTender: (id: string) => request<TenderView>(t(id)),
  createTender: (body: { title: string; buyer?: string; reference_no?: string; analysis_mode?: "focused" | "full" }) =>
    json<TenderView>("/tenders", "POST", body),
  uploadFiles: (id: string, files: File[], docRole?: string) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f, f.name);
    if (docRole) fd.append("doc_role", docRole);
    return request<{ files: { doc_id: string; filename: string; doc_role: string; status: string }[] }>(
      `${t(id)}/files`, { method: "POST", body: fd },
    );
  },
  ingestion: (id: string, version?: number) =>
    request<IngestionStatusResponse>(`${t(id)}/ingestion${qs({ version })}`),
  pageText: (id: string, docId: string, page: number) =>
    request<PageText>(`${t(id)}/files/${encodeURIComponent(docId)}/pages/${page}`),
  fileDownloadUrl: (id: string, docId: string) => `${API_BASE}${t(id)}/files/${encodeURIComponent(docId)}/download`,

  run: (id: string, body: { version?: number; analysis_mode?: "focused" | "full" } = {}) =>
    json<{ analysis_run_id: string; thread_id: string; tender_version: number }>(`${t(id)}/run`, "POST", body),
  getRun: (id: string, runId: string) => request<RunInfo>(`${t(id)}/runs/${encodeURIComponent(runId)}`),
  eventsJson: (id: string, runId: string, afterId = 0) =>
    request<Items<RunEvent> | RunEvent[]>(`${t(id)}/events${qs({ run_id: runId, after_id: afterId, format: "json" })}`),
  eventsUrl: (id: string, runId?: string, afterId = 0) =>
    `${API_BASE}${t(id)}/events${qs({ run_id: runId, after_id: afterId || undefined })}`,

  requirements: (id: string, params: { version?: number; category?: string; mandatory?: boolean; q?: string } = {}) =>
    request<{ version: number; analysis_mode: string; items: Requirement[] }>(`${t(id)}/requirements${qs(params)}`),
  keyFacts: (id: string, version?: number) => request<KeyFacts>(`${t(id)}/key-facts${qs({ version })}`),
  compliance: (id: string, version?: number) =>
    request<{ version: number; items: ComplianceItem[] }>(`${t(id)}/compliance${qs({ version })}`),
  risks: (id: string, version?: number) =>
    request<{ version: number; items: RiskItem[] }>(`${t(id)}/risks${qs({ version })}`),
  assessment: (id: string, version?: number) => request<BidAssessment>(`${t(id)}/assessment${qs({ version })}`),
  decide: (id: string, body: GateDecision) =>
    json<{ status: string; approval_status: string }>(`${t(id)}/decision`, "POST", body),
  versions: (id: string) => request<VersionsResponse>(`${t(id)}/versions`),
  compare: (id: string, a: number, b: number) => request<CompareResponse>(`${t(id)}/compare${qs({ a, b })}`),
  audit: (id: string) => request<Items<AuditEntry>>(`${t(id)}/audit`),
  ask: (id: string, question: string, version?: number) =>
    json<{ answer: string; citations: SourceSpan[] }>(`${t(id)}/ask`, "POST", { question, version }),

  // amendments
  uploadAmendment: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file, file.name);
    return request<{ amendment_id: string; doc_id: string; status: string; target_version: number }>(
      `${t(id)}/amendments`, { method: "POST", body: fd },
    );
  },
  amendments: (id: string) => request<Items<AmendmentSummary>>(`${t(id)}/amendments`),
  amendmentDiff: (id: string, aid: string) =>
    request<AmendmentDiff>(`${t(id)}/amendments/${encodeURIComponent(aid)}/diff`),
  confirmAmendment: (id: string, aid: string, body: { reviewer: string; comment?: string; accepted_change_ids?: string[] | null }) =>
    json<{ tender_version: number; status: string; superseded_reviews: number; stale_drafts: number }>(
      `${t(id)}/amendments/${encodeURIComponent(aid)}/confirm`, "POST", body,
    ),
  reanalyse: (id: string, version?: number) =>
    json<{ analysis_run_id: string; thread_id: string; tender_version: number }>(`${t(id)}/reanalyse`, "POST", {
      version,
      mode: "impact",
    }),

  // drafts / exports
  drafts: (id: string, version?: number) => request<Items<SectionDraft>>(`${t(id)}/drafts${qs({ version })}`),
  reviewDraft: (draftId: string, body: DraftReview) =>
    json<{ status: string }>(`/drafts/${encodeURIComponent(draftId)}/review`, "POST", body),
  exports: (id: string, version?: number) => request<Items<ExportInfo>>(`${t(id)}/exports${qs({ version })}`),
  generateExports: (id: string, version?: number, kinds?: string[]) =>
    json<Items<ExportInfo>>(`${t(id)}/exports`, "POST", { version, kinds }),
  exportUrl: (id: string, kind: string, version?: number) => `${API_BASE}${t(id)}/exports/${kind}${qs({ version })}`,

  // ops
  opsMetrics: (runId?: string) => request<OpsMetrics>(`/ops/metrics${qs({ run_id: runId })}`),
  opsGuardrails: (tenderId?: string) => request<Items<GuardrailEvent>>(`/ops/guardrails${qs({ tender_id: tenderId })}`),
  opsRuns: (tenderId?: string) => request<Items<RunInfo>>(`/ops/runs${qs({ tender_id: tenderId })}`),
  cancelRun: (runId: string) => json<{ cancelled: boolean }>(`/ops/runs/${encodeURIComponent(runId)}/cancel`, "POST"),
};

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

// TypeScript mirrors of backend/app/schemas/* (model_dump(mode="json")) and docs/api_contract.md.

export type Scope = "tender" | "kb";

export type IngestionStatus = "uploaded" | "validating" | "parsing" | "indexed" | "failed" | "quarantined";

export type TenderStatus =
  | "created" | "ingesting" | "ready_for_analysis" | "analyzing" | "awaiting_bid_decision"
  | "bid_approved" | "no_bid_approved" | "drafting" | "awaiting_draft_review" | "exported"
  | "amendment_pending" | "reanalysis_required" | "reanalyzing" | "failed";

export type EligibilityStatus =
  | "meets" | "meets_with_undertaking" | "meets_with_substitution" | "needs_action"
  | "partial" | "needs_human" | "gap";

export type RiskLevel = "within_policy" | "review" | "escalate";
export type Recommendation = "BID" | "BID_WITH_CONDITIONS" | "NO_BID";
export type ApprovalStatus = "pending" | "approved" | "rejected" | "superseded" | "review_required";

export interface SourceSpan {
  doc_id: string;
  page?: number | null;
  section_path?: string | null;
  text_span: string;
  char_start?: number | null;
  char_end?: number | null;
  file_sha256?: string | null;
  scope: Scope;
  tender_version?: number | null;
  sheet?: string | null;
  cell?: string | null;
}

export interface TenderView {
  tenderId: string;
  title: string;
  buyer?: string | null;
  referenceNo?: string | null;
  status: TenderStatus;
  currentVersion: number;
  analysisMode: "focused" | "full";
  ingestionStatus: "ingesting" | "ready_for_analysis" | "failed";
  analysisStatus: "not_started" | "running" | "awaiting_human" | "completed" | "failed";
  latestRunId?: string | null;
  latestAssessment?: {
    version: number;
    recommendation: Recommendation;
    score: number;
    hardGateFailures: string[];
  } | null;
  approvalStatus: ApprovalStatus;
  amendmentPending: boolean;
  submissionDeadline?: string | null;
  createdAt?: string | null;
}

export interface IngestionFile {
  doc_id: string;
  filename: string;
  doc_role: string;
  status: IngestionStatus;
  status_detail?: string | null;
  page_count?: number | null;
  flags: unknown[];
  version: number;
}

export interface IngestionStatusResponse {
  tender_id: string;
  status: string;
  ready: boolean;
  files: IngestionFile[];
}

export interface Requirement {
  requirement_id: string;
  tender_id: string;
  tender_version: number;
  clause_ref?: string | null;
  title: string;
  text: string;
  category: string;
  modality: string;
  mandatory: boolean;
  hard_gate: boolean;
  section_path?: string | null;
  source: SourceSpan;
  extra_sources: SourceSpan[];
  confidence: number;
  needs_review: boolean;
  superseded_by?: string | null;
  amended: boolean;
  parsed_rule?: Record<string, unknown> | null;
  tags: string[];
}

export interface Calculation {
  label: string;
  value: unknown;
  unit?: string | null;
}

export interface RuleResult {
  rule_kind: string;
  status: EligibilityStatus;
  summary: string;
  calculations: Calculation[];
  evidence: SourceSpan[];
  candidates: Record<string, unknown>[];
  actions: string[];
  needs_human_reason?: string | null;
  unknowns: string[];
}

export interface ComplianceItem {
  requirement_id: string;
  tender_id: string;
  tender_version: number;
  category: string;
  mandatory: boolean;
  hard_gate: boolean;
  status: EligibilityStatus;
  summary: string;
  rule_result?: RuleResult | null;
  tender_source: SourceSpan;
  company_evidence: SourceSpan[];
  owner?: string | null;
  actions: string[];
  confidence: number;
  checked_by: "rule" | "llm" | "human";
  reused_from_version?: number | null;
}

export interface RiskItem {
  risk_id: string;
  requirement_id?: string | null;
  tender_id: string;
  tender_version: number;
  category: string;
  level: RiskLevel;
  tender_value: string;
  policy_value: string;
  summary: string;
  approver?: string | null;
  approval_status: "pending" | "approved" | "rejected" | "not_required";
  source?: SourceSpan | null;
  reused_from_version?: number | null;
}

export interface CriterionScore {
  key: string;
  label: string;
  weight: number;
  raw_score: number;
  weighted: number;
  rationale: string;
  inputs: Record<string, unknown>;
}

export interface HardGateResult {
  requirement_id: string;
  label: string;
  status: string;
  passed: boolean;
  summary: string;
  evidence: SourceSpan[];
}

export interface BidAssessment {
  tender_id: string;
  tender_version: number;
  analysis_run_id: string;
  score: number;
  recommendation: Recommendation;
  criteria: CriterionScore[];
  hard_gates: HardGateResult[];
  hard_gate_failures: string[];
  conditions: string[];
  top_risks: string[];
  narrative: string;
  policy_version: string;
  analysis_mode: "focused" | "full";
  created_at?: string | null;
  approval_status?: ApprovalStatus;
}

export interface GateDecision {
  tender_version: number;
  action: "approve_bid" | "no_bid" | "defer";
  reviewer: string;
  comment?: string | null;
  conditions_accepted: string[];
}

export interface Money {
  amount_inr: number;
  display: string;
}

export interface KeyFacts {
  tender_id: string;
  tender_version: number;
  reference_no?: string | null;
  title?: string | null;
  buyer?: string | null;
  submission_deadline?: string | null;
  prebid_meeting?: string | null;
  bid_opening?: string | null;
  bid_validity_days?: number | null;
  estimated_value?: Money | null;
  emd?: Money | null;
  pbg_percent?: number | null;
  contract_period_months?: number | null;
  evaluation_method?: string | null;
  general_turnover_threshold?: Money | null;
  mse_turnover_threshold?: Money | null;
  mse_relaxation_allowed?: boolean | null;
  payment_terms?: string | null;
  penalty_cap_percent?: number | null;
  liability_cap?: string | null;
  facts: { name: string; value: unknown; source?: SourceSpan | null; confidence: number }[];
  missing: string[];
}

export type ChangeType =
  | "date_change" | "value_change" | "clause_replaced" | "clause_added" | "clause_deleted"
  | "clarification" | "eligibility_change" | "commercial_change" | "format_change" | "other";

export type ChangeKind = "added" | "changed" | "removed" | "superseded" | "clarified" | "no_change";

export interface AmendmentChange {
  change_id: string;
  change_type: ChangeType;
  kind: ChangeKind;
  part?: "A" | "B" | null;
  clause_ref?: string | null;
  field?: string | null;
  old_value?: string | null;
  new_value?: string | null;
  old_source?: SourceSpan | null;
  new_source: SourceSpan;
  affected_requirement_ids: string[];
  downstream_impacts: string[];
  summary: string;
  confidence: number;
  needs_review: boolean;
}

export interface DerivedImpact {
  impact_id: string;
  caused_by: string[];
  requirement_id?: string | null;
  check_key: string;
  before?: string | null;
  after?: string | null;
  summary: string;
  severity: string;
}

export interface AmendmentDiff {
  amendment_id: string;
  tender_id: string;
  base_version: number;
  target_version: number;
  changes: AmendmentChange[];
  derived_impacts: DerivedImpact[];
  invalidated_checks: string[];
  reusable_checks: string[];
  warnings: string[];
  generated_at?: string | null;
  status?: string;
}

export interface AmendmentSummary {
  amendment_id: string;
  status: string;
  base_version: number;
  target_version: number;
  doc_id?: string | null;
  changes?: number;
  confirmed_by?: string | null;
  created_at?: string | null;
}

export interface Claim {
  claim_id: string;
  text: string;
  citations: SourceSpan[];
  claim_type: string;
}

export interface ClaimVerdict {
  claim_id: string;
  verdict: "supported" | "unsupported" | "contradicted" | "conditional" | "unverifiable";
  reason: string;
  evidence: SourceSpan[];
}

export interface VerifierReport {
  draft_id: string;
  revision: number;
  verdicts: ClaimVerdict[];
  passed: boolean;
  feedback: string;
}

export interface SectionDraft {
  draft_id: string;
  tender_id: string;
  tender_version: number;
  section_key: string;
  title: string;
  body_markdown: string;
  claims: Claim[];
  placeholders: string[];
  revision: number;
  status: ApprovalStatus;
  stale: boolean;
  verifier?: VerifierReport | null;
}

export interface DraftReview {
  action: "approve" | "edit" | "reject" | "request_changes";
  reviewer: string;
  comment?: string | null;
  edited_markdown?: string | null;
}

export interface RunInfo {
  run_id: string;
  status: string;
  current_node?: string | null;
  mode: string;
  version: number;
  error?: string | null;
  usage?: Record<string, unknown>;
  started_at?: string | null;
  finished_at?: string | null;
  replay?: boolean;
  tender_id?: string;
}

export type RunEventName =
  | "run_started" | "node_started" | "node_completed" | "node_failed" | "human_review_required"
  | "run_completed" | "run_failed" | "amendment_diff_ready" | "budget_exceeded" | "file_status";

export interface RunEvent {
  id: number;
  event: RunEventName;
  tender_id: string;
  tender_version: number;
  analysis_run_id: string;
  node?: string | null;
  status?: string | null;
  message?: string | null;
  payload?: Record<string, unknown>;
  ts?: string;
}

export interface VersionInfo {
  version: number;
  status: string;
  amendment_id?: string | null;
  confirmed_by?: string | null;
  confirmed_at?: string | null;
  assessment?: { score: number; recommendation: Recommendation; approval_status: ApprovalStatus } | null;
  run_id?: string | null;
  run_status?: string | null;
}

export interface VersionsResponse {
  current_version: number;
  versions: VersionInfo[];
}

export interface CompareSide {
  version: number;
  score: number;
  recommendation: Recommendation;
  hard_gate_failures: string[];
}

export interface CompareVerdict {
  status: EligibilityStatus;
  summary: string;
}

export interface CompareResponse {
  a: CompareSide | null;
  b: CompareSide | null;
  changed_items: { requirement_id: string; hard_gate: boolean; before: CompareVerdict | null; after: CompareVerdict | null }[];
  risk_changes: { category: string; before: RiskLevel | null; after: RiskLevel | null; tender_value?: string | null }[];
  amendments: AmendmentChange[];
  derived_impacts: DerivedImpact[];
}

export interface AuditEntry {
  ts: string;
  actor: string;
  action: string;
  version?: number | null;
  target?: string | null;
  detail: Record<string, unknown>;
}

export interface ExportInfo {
  export_id: string;
  kind: string;
  version: number;
  created_at?: string | null;
}

export interface KbStatus {
  company_id: string;
  name: string;
  status: string;
  documents: number;
  chunks: number;
  by_type: Record<string, number>;
  facts: Record<string, number>;
  expiring: { kind: string; name: string; expiry_date: string; days_left: number }[];
  warnings: string[];
}

export interface KbDocument {
  doc_id: string;
  filename: string;
  doc_type?: string | null;
  page_count?: number | null;
  status: string;
  sensitivity: string;
  approved_for_reuse: boolean;
  live_subset: boolean;
}

export interface RetrievedChunk {
  chunk_id: string;
  doc_id: string;
  text: string;
  score: number;
  scope: Scope;
  page?: number | null;
  section_path?: string | null;
  parent_text?: string | null;
  metadata: Record<string, unknown>;
}

export interface ReadyResponse {
  ready: boolean;
  db: { ok: boolean; dialect?: string; pgvector?: boolean; error?: string };
  llm: { fast: string; strong: string; fast_configured: boolean; strong_configured: boolean };
  embeddings: { name: string; dim: number };
  demo_data: { exists: boolean; path: string };
  kb: { status: string };
}

export interface SettingsResponse {
  analysis_mode: "focused" | "full";
  demo_mode: boolean;
  llm: { fast: string; strong: string; fast_configured?: boolean; strong_configured?: boolean } | Record<string, unknown>;
  embedding_provider: string;
  max_cost_usd: number;
  max_llm_calls: number;
  company_id: string;
}

export interface GuardrailEvent {
  id?: number;
  ts?: string;
  tender_id?: string | null;
  run_id?: string | null;
  kind: string;
  severity: string;
  doc_id?: string | null;
  page?: number | null;
  excerpt?: string | null;
  detail?: string | null;
  quarantined: boolean;
  resolved?: boolean;
}

export interface OpsMetrics {
  run_id: string;
  llm: {
    calls: number;
    input_tokens: number;
    output_tokens: number;
    cost_usd: number;
    per_node?: Record<string, { calls: number; input_tokens: number; output_tokens: number; cost_usd: number }>;
  };
  latency_ms_by_node?: Record<string, number>;
  guardrail_events?: GuardrailEvent[];
  node_timings?: Record<string, unknown>;
  eval_results?: Record<string, unknown> | null;
}

export interface PageText {
  doc_id: string;
  page: number;
  text: string;
  flags: unknown[];
}

export interface Items<T> {
  items: T[];
}

/** Analysis graph nodes in run order (backend/app/agents/graph.py). */
export const NODE_ORDER = [
  "intake_guard",
  "load_tender",
  "shred_requirements",
  "merge_and_dedupe",
  "extract_key_facts",
  "reconcile_corrigenda",
  "route_requirements",
  "eligibility_and_risk",
  "bid_score",
  "gate1_review",
] as const;

export const NODE_LABELS: Record<(typeof NODE_ORDER)[number], string> = {
  intake_guard: "Intake checks",
  load_tender: "Load tender",
  shred_requirements: "Extract requirements",
  merge_and_dedupe: "Deduplicate",
  extract_key_facts: "Key facts",
  reconcile_corrigenda: "Apply corrigenda",
  route_requirements: "Route checks",
  eligibility_and_risk: "Eligibility & risk",
  bid_score: "Score",
  gate1_review: "Gate 1",
};

export type NodeName = (typeof NODE_ORDER)[number];

export const EXPORT_KINDS = [
  "compliance_xlsx",
  "eligibility_xlsx",
  "draft_docx",
  "dates_ics",
  "audit_json",
  "no_bid_docx",
] as const;

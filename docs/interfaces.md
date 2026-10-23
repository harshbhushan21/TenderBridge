# TenderBridge — Internal Interface Contract

> **Status (23 Oct).** This is the target contract. Only these modules exist today:
> `core.*`, `db.engine`, `db.models`, `db.repositories.*`, `db/migrations` (Alembic), `schemas.*`,
> `knowledge.kb_seed` (`seed_company_facts`, `fact_counts`), `scripts.{init_db,seed_company_facts}`,
> `ingestion.{hashes,file_validator,pdf_parser,docx_parser,xlsx_parser,ocr}`,
> `guardrails.{file_security,injection,pii}`, `llm.{factory,routing,budget}`,
> `retrieval.embeddings`, `tools.{date_normalization,facts,financial_rules,certificate_rules,tender_search,company_search}`
> (the two search tools import the not-yet-written `retrieval.hybrid` lazily),
> `agents.graph` + `agents.nodes.core` (partial graph, no interrupts),
> Phase 2: `tools.{rule_parser,project_rules,personnel_rules,registration_rules,commercial_rules,bid_scoring,rule_pack}`,
> Phase 3: `ingestion.{sectionizer,document_classifier,kb_ingest,upload_service,tender_ingest}`,
> `knowledge.freshness`, `retrieval.{chunker,indexer,filters,keyword,vector,hybrid,reranker,context_pack,query_rewrite}`,
> `services.tender_service.create_tender`, `scripts.ingest_company_kb`.
> `exports.*`, `ops.*`. Everything else below is **planned**; the README build plan
> gives each one a phase, task number and owner. Known deviations: graph order and
> roles (`docs/decisions.md` D3, D4); `llm.routing` does not yet read the `routing`
> section of `llm_routing_and_budget.json` (README task 4.1).

All modules import as `backend.app.<pkg>.<module>`. Python ≥ 3.13 (per `pyproject.toml`). Schemas in
`backend/app/schemas/*` and ORM models in `backend/app/db/models.py` are the
shared source of truth — **do not redefine them**; extend only by adding fields
with defaults.

Zero-setup defaults: SQLite DB (`storage/tenderbridge.db`), `hash` embeddings,
`fake:*` LLMs (every LLM call passes a deterministic `heuristic`), in-memory
LangGraph checkpointer, FastAPI background threads. Postgres/pgvector, real
LLMs, LangSmith, Docling/OCR are switched on purely via `.env`.

Optional heavy deps (docling, pytesseract, sentence-transformers, FlagEmbedding,
presidio, langchain provider packages, pgvector, langgraph-checkpoint-postgres)
MUST be imported lazily inside functions with graceful fallback.

---

## Foundation (written, stable)
- `core.config`: `get_settings()`, `load_demo_config(name)`. Paths: `demo_data_dir`, `company_kb_dir`,
  `structured_facts_dir`, `demo_config_dir`, `evaluation_dir` (evaluator ONLY), `tender_data_dir`,
  `uploads_dir`, `parsed_dir`, `exports_dir`, `replay_dir`.
- `core.errors`: `NotFoundError, ValidationFailed, ConflictError, InvalidStateError, FileRejected,
  PermissionDenied, BudgetExceeded, LLMOutputError, ToolError, ConfigError` (all `TenderBridgeError`).
- `core.logging`: `configure_logging`, `get_logger`, `log_event`, contextvars `request_id_var, tender_id_var, version_var, run_id_var`.
- `core.security`: `CurrentUser`, `get_current_user` (FastAPI dep), `role_can_read(role, allowed_roles)`, `safe_filename`, `ensure_within`.
- `db.engine`: `get_engine()`, `get_session()`, `session_scope()` (ctx manager), `db_dependency` (FastAPI), `init_db(drop=False)`, `check_db()`.
- `db.models`: all tables; `new_id(prefix)`, `utcnow()`.
- `llm.factory`: `structured_call(node, Schema, system=, user=, heuristic=) -> LLMResult`, `text_call(...)`,
  `load_prompt(name)` (reads `llm/prompts/<name>.md`), `prompt_version(name)`, `llm_status()`, `get_chat_model(node)`.
- `llm.budget`: `new_budget(run_id)`, `bind_budget(b)`, `get_budget(run_id=None)`, `cancel_run(run_id)`, `check_budget(node)`.
- `llm.routing`: `resolve(node) -> NodeRoute`.
- `retrieval.embeddings`: `get_embedder()` (`.embed_documents`, `.embed_query`, `.name`, `.dim`), `tokenize(text)`, `cosine(a,b)`.

---

## Workstream A — ingestion / knowledge / retrieval / input guardrails
- `guardrails.file_security.validate_upload(filename: str, data: bytes, *, allowed: set[str]|None=None) -> dict`
  returns `{"mime": str, "sha256": str, "ext": str, "size": int}`; raises `FileRejected`. Handles ZIP limits.
- `guardrails.injection.scan_text(text, *, doc_id=None, page=None) -> list[GuardrailFlag]`;
  `scan_pdf_hidden_text(path) -> list[GuardrailFlag]` (white/tiny/off-page text via PyMuPDF);
  `strip_quarantined(text, flags) -> str`; `wrap_untrusted(text, source) -> str` (delimits document text for prompts).
- `guardrails.pii.mask_pii(text) -> str`; `mask_obj(obj) -> obj`.
- `ingestion.hashes.sha256_bytes(data)`, `sha256_file(path)`.
- `ingestion.pdf_parser.parse_pdf(path, doc_id) -> ParsedDocument` (Docling → PyMuPDF → pypdf; OCR pages without text).
- `ingestion.docx_parser.parse_docx(path, doc_id)`, `ingestion.xlsx_parser.parse_xlsx(path, doc_id) -> tuple[ParsedDocument, list[BoqItem]]`.
- `ingestion.ocr.ocr_page(pdf_path, page_no) -> str` (pytesseract optional; returns "" if unavailable).
- `ingestion.sectionizer.sectionize(doc: ParsedDocument) -> list[ParsedSection]` (numbered headings, PQ-xx, tables kept whole).
- `ingestion.document_classifier.classify_tender_file(filename, first_text) -> TenderDocRole`; `classify_kb_file(rel_path) -> str`.
- `ingestion.upload_service`:
  - `save_tender_upload(session, tender_id, filename, data, *, doc_role=None, version=1, amendment_id=None, actor="system") -> TenderFile`
  - `process_tender_file(doc_id) -> None` (opens own session; validating→parsing→indexed|failed|quarantined; emits `ops.events.emit_event(... event="file_status")`)
  - `tender_ingestion_status(session, tender_id, version=None) -> dict` → `{"tender_id","status","files":[{doc_id,filename,doc_role,status,status_detail,page_count,flags,version}], "ready": bool}`
- `ingestion.tender_ingest`: `ingest_tender_file(session, tf: TenderFile) -> ParsedDocument`;
  `load_effective_sections(session, tender_id, version, *, include_quarantined=False) -> list[ParsedSection]`
  (sections from files with `version <= version`); `load_sections_for_doc(session, doc_id)`.
- `ingestion.kb_ingest.ingest_company_kb(session, company_id=None, *, kb_dir=None, manifest_path=None, facts_dir=None, force=False) -> dict` (hash-idempotent, manifest-driven; poisoned docs quarantined, not indexed).
- `knowledge.kb_seed.seed_company_facts(session, company_id=None, *, facts_dir=None) -> dict` (idempotent upsert from `structured_facts/*`).
- `knowledge.fact_provenance.attach_evidence(...)`, `knowledge.fact_validation.validate_facts_against_sources(session, company_id) -> dict`,
  `knowledge.freshness.expiring_credentials(session, company_id, within_days=90, as_of=None) -> list[dict]`, `kb_status(session, company_id) -> dict`.
- `retrieval.chunker.chunk_sections(sections, *, child_tokens=250, overlap=40) -> list[ChunkRecord]` (parents `is_parent` + children with `parent_id`).
- `retrieval.indexer.index_tender_chunks(session, tender_id, version, doc_id, chunks)`, `index_kb_chunks(session, company_id, kb_doc, chunks)`, `delete_doc_chunks(...)`.
- `retrieval.keyword.bm25_search(...)` (BM25 over SQL-filtered candidates, both DBs), `retrieval.vector.vector_search(...)` (pgvector SQL or in-Python cosine), `retrieval.query_rewrite.expand_query(q)`.
- `retrieval.hybrid.hybrid_search(session, scope: Scope, query, *, k=6, tender_id=None, version=None, company_id=None, role="bid_manager", doc_types=None, approved_only=False) -> list[RetrievedChunk]` (filters BEFORE ranking; RRF; optional rerank; parent text attached).
- `retrieval.reranker.rerank(query, chunks) -> chunks` (no-op unless RERANKER set).
- `retrieval.context_pack.build_context(chunks, *, max_chars=12000) -> str` (each chunk prefixed `[doc_id p.N | section]`).

## Workstream B — tools / rules / verification guardrails
- `tools.date_normalization`: `parse_date(text) -> date|None`, `parse_datetime(text) -> datetime|None`,
  `parse_money(text) -> Money|None`, `to_inr(value, unit) -> float` (₹, Rs, lakh/lac/L, crore/cr/Cr, million),
  `format_inr(inr, unit="crore") -> str`, `fiscal_year_key(label) -> int`, `years_between(a, b) -> float`.
- `tools.facts`: `get_company, get_financials, get_certificates, get_projects, get_people, get_risk_positions`
  (session, company_id, ...) → schema records; `get_key_facts(session, tender_id, version)`, `save_key_facts(...)`,
  `get_requirement(session, tender_id, version, requirement_id)`, `query_facts(session, view, company_id, **filters)` (allow-listed views only).
- `tools.tender_search.search_tender(session, tender_id, version, query, *, k=6, role="bid_manager")`
- `tools.company_search.search_company_kb(session, company_id, query, *, k=6, role="bid_manager", approved_only=False, doc_types=None)`
- `tools.financial_rules.check_turnover(financials, rule: TurnoverRule, company: CompanyProfile) -> RuleResult`; `check_net_worth(financials, rule)`.
- `tools.certificate_rules.normalize_standard(name) -> str`; `check_certification(certs, rule: CertificationRule, key_facts: KeyFacts|None) -> RuleResult`.
- `tools.project_rules.find_qualifying_projects(projects, rule: SimilarWorkRule, *, similarity_fn=None) -> RuleResult` (uses `eligible_value_inr`, window from reference date, scope tags; `needs_human` when similarity ambiguous).
- `tools.personnel_rules.check_personnel(people, rule: PersonnelRule) -> RuleResult`.
- `tools.registration_rules.check_document(company: CompanyProfile, rule: DocumentPresenceRule, *, kb_doc_types: set[str]) -> RuleResult`.
- `tools.commercial_rules.get_risk_position(positions, category)`; `assess_commercial_term(*, category, tender_value, tender_text, positions, tender_id, version, requirement_id, source) -> RiskItem`; `detect_commercial_category(text) -> tuple[str, float|None]|None`.
- `tools.rule_parser.parse_rule(req: Requirement, key_facts: KeyFacts|None) -> EligibilityRule|None` (regex: thresholds, MSE relaxation, OR branches "three … OR two … OR one …", windows, cert standards, roles).
- `tools.amendment_diff`: `diff_amendments(*, amendment_sections, base_requirements, base_key_facts, amendment_id, tender_id, base_version, target_version) -> AmendmentDiff`;
  `apply_amendments(requirements, key_facts, diff, *, accepted_ids=None) -> tuple[list[Requirement], KeyFacts]`;
  `invalidation_for(diff) -> tuple[list[str], list[str]]` (check keys: `key_facts.deadline`, `certification.valid_at_submission`, `commercial.<cat>`, `turnover`, `similar_work`, `personnel`, `score`, ...).
- `tools.citation_lookup.lookup_citation(session, span: SourceSpan) -> dict` → `{found, text, page, doc_id, match_score}`.
- `tools.boq.get_boq_items(session, tender_id, version, sheet=None) -> list[BoqItem]`.
- `tools.bid_scoring`: `load_scoring_policy() -> BidScoringPolicy`; `calculate_bid_score(compliance, risks, policy, *, tender_id, version, run_id, key_facts=None, analysis_mode="focused") -> BidAssessment` (hard gate failure ⇒ NO_BID always).
- `tools.registry.get_langchain_tools(session_factory, *, tender_id, version, company_id, role) -> list[BaseTool]` (read-only tools for ask_tender).
- `guardrails.citation_verifier.verify_citations(session, spans) -> list[dict]`.
- `guardrails.claim_verifier.check_claims_deterministic(session, draft: SectionDraft, *, company_id, key_facts) -> list[ClaimVerdict]`; `extract_claims(markdown) -> list[Claim]`.
- `guardrails.tool_allowlist.ALLOWED_TOOLS: dict[node, set[tool]]`, `assert_allowed(node, tool)`.
- `guardrails.policy_enforcer`: `enforce_hard_gates(assessment) -> BidAssessment`, `assert_no_outbound(action)`, `ensure_version_bound(decision_version, current_version)`.

## Workstream C — agents (LangGraph)
Node names (SSE `node` values, in order):
`intake_guard, load_tender, shred_requirements, merge_and_dedupe, extract_key_facts, reconcile_corrigenda, route_requirements, eligibility_and_risk, bid_score, human_gate_1, write_no_bid_report, plan_response, write_sections, verify_claims, rewrite_failed, human_gate_2, final_compliance_check, export_outputs`.
- `agents.state` re-exports `TenderState`.
- `agents.graph.build_graph(checkpointer=None)`, `get_graph()` (compiled singleton), `get_checkpointer()` (postgres → sqlite → memory).
- `agents.runner`:
  - `start_analysis(tender_id, version, *, mode="full_analysis"|"impact", analysis_mode=None, previous_run_id=None, actor="system") -> str` (creates `AnalysisRun`, thread_id, runs in background thread, returns run_id)
  - `resume_gate1(run_id, decision: GateDecision, actor) -> None`, `resume_gate2(run_id, section_key, review: DraftReview, actor) -> None`
  - `get_run(run_id) -> dict`, `get_run_state(run_id) -> dict`, `latest_run(session, tender_id, version=None) -> AnalysisRun|None`, `cancel(run_id)`.
- `agents.persistence`: writes `RequirementRow, KeyFactsRow, ComplianceItemRow, RiskItemRow, BidAssessmentRow, ResponsePlanRow, SectionDraftRow`; readers `load_requirements(session, tender_id, version, run_id=None)`, `load_compliance(...)`, `load_risks(...)`, `load_assessment(...)`, `load_drafts(...)`.
- `agents.subgraphs.requirement_router` (dispatch per requirement to rule tools / LLM graders), `agents.subgraphs.amendment_impact` (derived impacts v_prev vs v_new).
- `agents.ask_tender.ask(tender_id, version, question, role) -> dict` (read-only).

## Workstream D — API / ops / repositories / services / scripts
- `ops.events.emit_event(*, run_id, tender_id, version, event, node=None, status=None, message=None, payload=None)` (persists `RunEvent`, publishes to in-process pub/sub, thread-safe);
  `async subscribe(run_id|tender_id) -> AsyncIterator[dict]`; `list_events(session, run_id, after_id=0)`.
- `ops.audit.audit(actor, action, *, tender_id=None, version=None, run_id=None, target=None, **detail)`.
- `ops.metrics.record_model_usage(run_id, node, model, tier, input_tokens, output_tokens, cost_usd, latency_ms, ok, error=None)`;
  `record_guardrail(flag: GuardrailFlag, *, tender_id=None, run_id=None, session=None)` (pass `session` inside an open transaction); `run_metrics(session, run_id) -> dict`.
- `ops.langsmith.configure_tracing()`, `traceable(name)` (no-op if langsmith absent), `redact(obj)`.
- `services.tender_service`, `services.amendment_service` (upload corrigendum → diff → confirm → new version → supersede approvals, stale drafts).
- API routes per Phase 9 table; `backend/app/main.py` app factory.

## Workstream E — exports / evals / docs / root files
- `exports.compliance_xlsx.write_compliance_xlsx(path, *, tender_id, version, requirements, compliance, risks, key_facts=None, analysis_mode="focused") -> Path` (sheets: Compliance Matrix, Submission Checklist)
- `exports.compliance_xlsx.write_eligibility_xlsx(path, *, tender_id, version, compliance, risks, assessment) -> Path`
- `exports.draft_docx.write_draft_docx(path, *, tender_id, version, drafts, assessment=None) -> Path`; `write_no_bid_docx(path, *, assessment, report: dict) -> Path`
- `exports.dates_ics.write_dates_ics(path, key_facts) -> Path`
- `exports.audit_json.write_audit_json(path, *, tender_id, version, run_id, payload: dict) -> Path`
- `exports.service.export_outputs(session, tender_id, version, run_id, *, kinds=None) -> list[dict]` (reads persisted rows via `agents.persistence` loaders, writes to `storage/exports/<tender>/v<version>/`, inserts `ExportRow`, returns `{export_id, kind, path}`).

## Workstream F — frontend (Next.js + TS + Tailwind)
Talks only to the API (`NEXT_PUBLIC_API_BASE`, default `http://localhost:8000`). JSON bodies are the Pydantic schema dumps above.

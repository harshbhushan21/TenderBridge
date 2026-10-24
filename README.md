# TenderBridge

**An agentic copilot that turns an IT-infrastructure tender pack into a
verified compliance matrix, a bid / no-bid recommendation and a cited first
draft, with a human approving every decision.**

AgentOps 2026 · Track 01 (Multi-agent systems) · CGI domain: IT Infrastructure ·
Team BR01/MP04 (HX-2SJA)

TenderBridge reads a tender, extracts every requirement with its page, checks
each one against a persistent company knowledge base (KB) using the right
method (deterministic rules for numbers and dates, hybrid RAG for evidence),
scores the bid, and stops for a human decision. When a corrigendum arrives it
diffs the change, re-runs only the affected checks, and shows how the
recommendation moved.

> **Demo data is synthetic.** `TDR-001` is a simulated State Data Centre O&M
> tender (fictional buyer), and Nimbus Digital Services is a fictional bidder.
> Nothing here is CGI data, and TenderBridge never submits anything to GeM,
> CPPP or any other portal.

> **Status (24 Oct 2026):** Phases 1-9 are built and tested (the Phase 9 deck is
> deferred): upload, hybrid retrieval, the agent graph to Gate 1, the corrigendum
> workflow, the web UI with Knowledge Base and AgentOps pages, guardrails, evals
> and optional LangSmith tracing. Real LLM keys are not configured yet (the app
> runs offline with deterministic fallbacks). Phases 10-12 remain. The
> [build plan](#build-plan) below is the source of truth.

## Contents

1. [Team](#team)
2. [The demo in one paragraph](#the-demo-in-one-paragraph)
3. [Architecture](#architecture)
4. [Design rules](#design-rules-non-negotiable)
5. [Build plan](#build-plan) (phases, owners `[S]`/`[H]`, status)
6. [Schedule](#schedule-23--24-oct)
7. [Repository layout](#repository-layout)
8. [Setup](#setup)
9. [Configuration](#configuration)
10. [Demo data and expected results](#demo-data-and-expected-results)
11. [Testing and evaluation](#testing-and-evaluation)
12. [Security and data handling](#security-and-data-handling)
13. [Working together](#working-together)
14. [Reference docs](#reference-docs)

## Team

| Tag | Member | Owns |
|---|---|---|
| **[H]** | Harsh Bhushan (team leader), MIT Bengaluru, 3rd year | Agent graph (LangGraph), deterministic rules and scoring, guardrails, LangSmith tracing and evals |
| **[S]** | Swarnim Rai, MIT Bengaluru, 3rd year | Ingestion and RAG pipeline, facts store, FastAPI backend, frontend UI |

Each build phase has exactly one owner, and ownership alternates [S] → [H]
so the two of us never edit the same phase at once.

## The demo in one paragraph

The Nimbus KB is onboarded once (52 documents, structured facts with source
spans). The bid manager creates a tender workspace and uploads the original
notice, RFP, annexures and BoQ (**v1**; the corrigendum is held back). After
ingestion they click **Analyze**: requirements stream in live, eligibility is
checked (turnover passes only through the MSE relaxation, similar work passes
through OR-branch (b), ISO 27001 is valid with a 4-day margin) and the result
is **BID_WITH_CONDITIONS, 77.34**. The bid manager approves at **Gate 1**; an
analyst cannot. Then they upload **Corrigendum No. 1** to the same tender,
preview the typed diff, confirm it, and re-analyse impact: the deadline moves
from 6 Nov to 20 Nov, ISO 27001 expires on 10 Nov, so the hard gate fails.
The weighted score rises to 78.80 but the recommendation becomes **NO_BID**.
The v1 approval is superseded, any v1 draft is marked stale, and the AgentOps
tab shows traces, cost, eval scores and guardrail events.

## Architecture

```text
Next.js UI  (dashboard · KB · tender workspace · amendments · AgentOps)
   │  REST + SSE  (docs/api_contract.md)
FastAPI  ── services ── repositories ── SQLAlchemy
   │
LangGraph analysis graph (runner in a background thread, checkpointed)
   intake_guard → load_tender → shred_requirements → merge_and_dedupe
   → extract_key_facts → reconcile_corrigenda → route_requirements
   → eligibility_and_risk → bid_score → human_gate_1 (interrupt)
        ├─ no bid → write_no_bid_report → finalize
        └─ bid → plan_response → write_sections → verify_claims
                 ↺ rewrite_failed (max 2) → human_gate_2 (interrupt)
                 → final_compliance_check → export_outputs → finalize
   │
   ├─ deterministic tools: facts, money/dates, turnover, certificates,
   │  similar work (OR rules), personnel, commercial risk, amendment diff,
   │  bid scoring  ← authoritative for numbers, dates and hard gates
   ├─ hybrid retrieval: tender_chunks | kb_chunks (never mixed), role filter
   ├─ LLM tiers: fast = Groq GPT-OSS 20B · strong = Groq GPT-OSS 120B ·
   │  drafting = Gemini 3 Flash · injection screen = Prompt Guard 2
   └─ guardrails, budgets, audit log, metrics, LangSmith
Storage: SQLite (zero-setup) or PostgreSQL 16 + pgvector
demo_data/ (read-only fixtures)   storage/ (ignored, writable runtime)
```

The full design (25 pages, 9 diagrams) is the architecture reference shared
with the team. The build follows the final implementation action plan, whose
principles are summarised below and whose deviations are logged in
[`docs/decisions.md`](docs/decisions.md).

## Design rules (non-negotiable)

1. The company KB is onboarded **once** and reused across tenders and versions.
2. **Upload ≠ Analyze.** Upload validates, parses and indexes; Analyze runs the graph.
3. Amendments belong to the **same tender**: upload → preview diff → confirm → incremental re-analysis → new version.
4. Tender and company text live in **separate retrieval scopes**.
5. **SQL facts are authoritative** for amounts, dates, certificates, personnel and projects. RAG finds evidence; rules decide eligibility.
6. Every fact, requirement, verdict and draft claim carries **document ID, page and text span**.
7. A **failed mandatory gate overrides** any weighted score.
8. **Gold labels never reach agent context**: `demo_data/evaluation/` is evaluator-only.
9. Documents are **untrusted data**; instructions inside them are quarantined, never obeyed.
10. Approvals are **version-bound**: a material amendment supersedes them and marks drafts stale.
11. No agent can submit to a portal, send email, or write to the KB.
12. Be honest on stage: synthetic data, focused live analysis (42 of 105 requirements), metrics are targets until measured.

## Build plan

We build **one phase at a time**. Each phase has **one owner** and the owner
alternates: odd phases are **[S]** Swarnim, even phases are **[H]** Harsh.
A phase only depends on phases before it, so the owner never waits on the
other person mid-phase. While one person builds, the other does the
non-code prep listed under **Meanwhile** (reviewing and testing the previous
phase, preparing data checks, deck, script).

Legend: ✅ done · 🟡 partial (code exists, not wired or not tested) · ⬜ to do.
Rubric tags: Reuse, RAI (Responsible AI), ROI, MVP, Orig (Originality).

| Phase | Owner | Focus | Rubric | Est. |
|---|---|---|---|---|
| 0 | — | Groundwork (done) | MVP | — |
| 1 | [S] | Repo hygiene, roles, fact seeding | MVP, Reuse | 1.5 h |
| 2 | [H] | Deterministic rules and bid scoring | Orig, Reuse | 2.5 h |
| 3 | [S] | KB ingestion, hybrid retrieval, tender upload | MVP, RAI | 3 h |
| 4 | [H] | Agent graph to Gate 1, runner, persistence | MVP, RAI | 3 h |
| 5 | [S] | API for the v1 lifecycle | MVP | 2 h |
| 6 | [H] | Corrigendum, versioning, incremental re-analysis | Orig | 2.5 h |
| 7 | [S] | Frontend core + amendment/version routes | MVP | 2.5 h |
| 8 | [H] | Trust layer: guardrails, claim verifier, evals, measured run | RAI, ROI | 2 h |
| 9 | [S] | KB + AgentOps pages, export tests, README, deck | ROI, Reuse | 1.5 h |
| 10 | [H] | *Stretch:* cited drafting + Gate 2 backend | MVP | 1.5 h |
| 11 | [S] | *Stretch:* draft review UI + routes | MVP | 1 h |
| 12 | [H] | Demo script, replay fallback, final evals, video | All | 1 h |

Estimates are rough planning numbers, not commitments.

**Critical path (never cut):** Phases 1 → 9 and 12. Phases 10–11 (drafting)
are the first thing to cut; inside other phases cut UI polish, then the
second rule pack, then the ask-the-tender chat.

### Phase 0 · Groundwork (done)

Built before this plan; listed so later phases know what to reuse.

| Item | Status |
|---|---|
| Settings and path resolution, errors, structured logging (`core/`) | ✅ |
| Pydantic schemas: documents, requirements, eligibility, assessment, amendments, graph state | ✅ |
| ORM models; DB engine with SQLite default and Postgres + pgvector support | ✅ |
| Repositories for KB, tenders, amendments, analysis, audit | ✅ |
| Demo data pack under `demo_data/` | ✅ |
| Parsers: PDF (Docling → PyMuPDF → pypdf), DOCX, XLSX, OCR; SHA-256 hashing | ✅ |
| Upload validation, hidden-text/injection scans, PII masking | ✅ |
| Embedding abstraction (offline `hash` default) | ✅ |
| Facts tools; date/money normalisation; turnover, net-worth and certificate rules | ✅ |
| LLM factory (fast/strong tiers, structured output, fake mode, budget) | ✅ |
| Partial graph to bid score / no-bid report, no interrupts (→ Phase 4) | 🟡 |
| Events, audit, metrics, LangSmith helpers (not wired → Phases 4, 8) | 🟡 |
| Export writers: XLSX, DOCX, ICS, audit JSON (untested → Phase 9) | 🟡 |
| Frontend package + typed client, SSE helper, types (`frontend/src/lib/`) | ✅ |

### Phase 1 · [S] Repo hygiene, roles and fact seeding

| # | Task | Status |
|---|---|---|
| 1.1 | Rename package `testtbridge` → `tenderbridge`; remove the `src/testtbridge` stub and script entry; non-installable app (`[tool.uv] package = false`); re-locked | ✅ |
| 1.2 | Dev tools (pytest, ruff, mypy) in a `dev` group; `langchain-groq` added; stale `requirements.txt` deleted (`pyproject.toml` + `uv.lock` are the source) | ✅ |
| 1.3 | Roles in `core/security.py`: `analyst / writer / bid_manager / admin`, data scopes `hr / finance / legal`; unknown `X-Role` → `analyst`; `require_approver()` for gates (see [Roles](#roles)) | ✅ |
| 1.4 | `knowledge/kb_seed.py`: idempotent upsert of `structured_facts/*` (3 financials, 5 certificates, 10 projects, 10 people, 10 risk positions, 62 evidence rows) | ✅ |
| 1.5 | `backend/scripts/init_db.py`, `seed_company_facts.py`; audit repository | ✅ |
| 1.6 | `Makefile`: `setup`, `init-db`, `migrate`, `seed`, `reset-db`, `test`, `lint` (later phases add theirs) | ✅ |
| 1.7 | Alembic baseline `7725f771faec` (pgvector extension + GIN indexes on Postgres); upgrade / `alembic check` / downgrade verified on SQLite and Postgres | ✅ |
| 1.8 | Postgres 16 + pgvector 0.8.0 in `docker-compose.yml` (port 5433); `make db-up`, `test-pg`; tests isolated from the dev DB (`TEST_DATABASE_URL`) | ✅ |
| 1.9 | Pinned ruff rule set and mypy config in `pyproject.toml`; existing backend lint-clean (safe fixes only, behaviour unchanged); `make lint`, `make typecheck`. mypy is clean for Phase 1 files; 38 typing errors remain in later-phase files, assigned as tasks 2.8, 3.9, 4.9, 8.7, 9.6 | ✅ |
| 1.10 | Portable across machines and OSes: `dev.py` task runner + `doctor`, `.python-version`, `.gitattributes`, root-anchored SQLite path, fixed Docker project name, Node pin; verified with a fresh clone in another folder and a real `git clone` with `core.autocrlf=true` | ✅ |

**Done when:** `uv sync` works on a fresh clone, seeding twice gives the same row counts, `get_financials()` returns ₹46 / 52 / 58 Cr with spans, and `role_can_read("analyst", …)` follows the data pack's tags.
**Result (23 Oct):** ✅ done. Verified on a clean copy (`make setup && make seed && make test`) and on a fresh Postgres volume (`make db-up && make migrate && make seed`, seeding twice gives identical counts). 20 tests pass on Postgres (`make test-pg`), 19 + 1 Postgres-only skip on SQLite; `make lint` is clean. Notes for Phase 2: facts are keyed by company `NIMBUS-001`; `Project.eligible_value_inr` is the client-certified bidder share only (PRJ-005 is `None`); project `scope_tags` are factual (`data_centre`, `noc_24x7`, `sector:*`, `scope:*`) and similarity is for the rule/judge to decide; every source column is kept in each row's `raw` (e.g. `revenue_infra_services_inr_cr` for PQ-04); person names are stored masked.
**Meanwhile [H]:** write the Phase 2 test cases from `eligibility_gold.json` and `eligibility_rules_gold.json`; confirm Groq/Gemini model IDs and quotas with a tiny request.

### Phase 2 · [H] Deterministic rules and bid scoring

| # | Task | Status |
|---|---|---|
| 2.1 | Unit tests for the existing tools: lakh↔crore, dates, fiscal years, turnover (MSE), certificate validity | ✅ |
| 2.2 | `tools/rule_parser.py`: requirement text → structured rule (`field, operator, threshold, window, aggregation, logic`), incl. MSE relaxation and "three … OR two … OR one …" | ✅ |
| 2.3 | `tools/project_rules.py`: PQ-05 OR branches on certified eligible value, 7-year window, scope tags; PRJ-005 `needs_human`, PRJ-004 out of window, PRJ-009 not similar | ✅ |
| 2.4 | `tools/personnel_rules.py` (HR tracker beats CV; NDS-E105 → suggest NDS-E110) and `registration_rules.py` (Udyam, OEM letter, declarations) | ✅ |
| 2.5 | `tools/commercial_rules.py`: clause category vs `risk_positions.json` → `within_policy / review / escalate` | ✅ |
| 2.6 | `tools/bid_scoring.py`: hard gates + weights from `bid_scoring_policy.json`; any hard-gate gap ⇒ `NO_BID` | ✅ |
| 2.7 | Rules as a config **rule pack** (GeM/CPPP) so a second pack loads without code changes | ✅ |
| 2.8 | mypy-clean `tools/financial_rules.py`, `tools/facts.py` (typing only; no runtime bugs found) | ✅ |

**Result (23 Oct):** ✅ done. Added deterministic parsing and evaluation for financial, project, certificate, personnel, registration, and commercial requirements, plus policy-driven weighted scoring with hard-gate precedence. The six Phase 2 acceptance tests pass with the LLM off: ₹52 Cr passes ₹45 Cr and fails ₹55 Cr, PQ-05 branch (b) passes, ISO is valid on 6 Nov and expired on 20 Nov, and scoring returns 77.34 `BID_WITH_CONDITIONS` (v1) and 78.80 `NO_BID` (v2). Alternate rule packs can be selected with `RULE_PACK_PATH`.
**Review fixes (23 Oct, [S]):** checking each tool against `eligibility_gold.json` found and fixed: bid-specific MAF (`tender_specific`) returned `gap` instead of `needs_action`, and the scorer counted any non-`meets` hard gate as failed, either of which turned v1 into NO_BID; `commercial_risk` averaged deductions instead of summing them (94.44 vs gold 50); `eligibility_confidence` averaged all items instead of hard gates; PRJ-005's ₹38 Cr consortium total counted as pending in branches (b) and (c) instead of its 45% share; the Project Manager failed on availability at the bid deadline (now `PersonnelRule.available_by`); Security Lead returned `meets` instead of `meets_with_substitution` and hardcoded `NDS-E110`; the office undertaking returned `needs_action` instead of `meets_with_undertaking`; escalated deal-breaker clauses now add a condition; the parser reads word numbers ("seven years") and every standard in "ISO 9001 and ISO/IEC 27001". `test_phase2_gold_regressions.py` derives v1 / v2 / X1 scores and verdicts from the gold verdicts through the real `bid_score` node.
**Meanwhile [S]:** read the Phase 2 code, list which tools Phase 3 retrieval must feed; sketch the UI screens on paper.

### Phase 3 · [S] KB ingestion, hybrid retrieval and tender upload

| # | Task | Status |
|---|---|---|
| 3.1 | `ingestion/sectionizer.py` (headings from font size/weight, DOCX/XLSX `#` headings, text-pattern fallback; running headers removed; wrapped headings merged; page offsets kept) and `document_classifier.py` (first-page text, then filename) | ✅ |
| 3.2 | `ingestion/kb_ingest.py`: manifest-driven, hash-idempotent; names masked from HR facts + regex PII; per-section reuse approval for past proposals; a KB document with hidden/injected text is quarantined and not indexed | ✅ |
| 3.3 | `retrieval/`: chunker (~250-token children, ≤1,200-token parents), indexer, filters (role/scope/version/quarantine before ranking), BM25 keyword, pgvector/in-Python vector, RRF k=60, one result per parent with parent text, `query_rewrite` (acronyms + phrasing), context_pack (`[S1]` labels); reranker optional | ✅ |
| 3.4 | `knowledge/freshness.py`: `kb_status()` and `expiring_credentials()` (ISO 27001 → 10 Nov 2026 warning) | ✅ |
| 3.5 | `ingestion/upload_service.py`: save → validate → parse → hidden-text + injection scan → section → index; per-file status and `file_status` events; corrigendum rejected on the v1 path by name and, if renamed, by content; `services/tender_service.create_tender` | ✅ |
| 3.6 | `ingestion/tender_ingest.py`: `load_effective_sections`, `load_sections_for_doc`, `load_boq_items` (29 rows from the price schedule, with cell refs) | ✅ |
| 3.7 | `tests/integration/test_phase3_ingestion.py` (18 tests): all 93 reference headings found with matching start pages; scanned page OCR'd; KB idempotent (second run skips 52); no real names in the index; reuse flags; poisoned KB doc quarantined; injection trap stripped from tender chunks with guardrail events; role filter; tender isolation; gold retrieval recall | ✅ |
| 3.8 | `dev.py ingest-kb` (`make ingest-kb`) seeds facts and ingests the KB | ✅ |
| 3.9 | mypy-clean `retrieval/embeddings.py`, `ingestion/docx_parser.py` (and every new Phase 3 module) | ✅ |

**Done when:** the four v1 files ingest to `ready_for_analysis` with page-citable sections and BoQ rows, with no recommendation yet, and KB queries return the right doc and page.
**Result (23 Oct):** ✅ done. Measured on `retrieval_qa.json` with the offline hash embedder: **company recall@6 20/20 (MRR 0.90)** and **tender recall@6 12/12 (MRR 0.73)** on the questions answerable from v1 (the 7 corrigendum questions are measured in Phase 6). Same results on SQLite and Postgres. KB ingest: 52 documents, 782 chunks, ~8 s; re-run skips all. v1 upload: notice (4 sections), RFP (67), annexures (26, page 12 OCR'd), price schedule (4 sheets, 29 BoQ rows). Notes for Phase 4: read sections with `load_effective_sections(session, tender_id, version)` (quarantined sections excluded); search with `tools.tender_search.search_tender` / `tools.company_search.search_company_kb`; wrap any document text in `guardrails.injection.wrap_untrusted` before it reaches a prompt; `PersonnelRule.available_by` is the takeover date, `as_of` the bid deadline.
**Meanwhile [H]:** write the shredder / router / similarity-judge prompts for Phase 4 and test them by hand on two sections.

### Phase 4 · [H] Agent graph to Gate 1, runner and persistence

| # | Task | Status |
|---|---|---|
| 4.1 | Routing loader reads the `routing` section of `llm_routing_and_budget.json` (per-node model, prices); Groq smoke test | ✅ |
| 4.2 | Reorder to `extract_key_facts → reconcile_corrigenda` (decision D4) | ✅ |
| 4.3 | Prompts in `llm/prompts/`; real LLM calls in shred / key facts / route; recall-first two-pass extraction incl. tables | ✅ |
| 4.4 | `agents/subgraphs/requirement_router.py`: dispatch to Phase 2 tools or the RAG grader; `Send()` fan-out with a concurrency cap | ✅ |
| 4.5 | Gate 1 as `interrupt()` + `Command(resume=…)`; checkpointer (Postgres → SQLite → memory) | ✅ |
| 4.6 | `agents/runner.py` (background start, resume, cancel, run state) and `agents/persistence.py` (write/read results) | ✅ |
| 4.7 | Events and audit emitted per node | ✅ |
| 4.8 | `backend/scripts/run_demo_case.py CASE-1`; `Makefile`: `demo-cli` | ✅ |
| 4.9 | mypy-clean `agents/nodes/core.py`, `ops/events.py`, `llm/factory.py`, `exports/service.py` (its `agents.persistence` import resolves with 4.6) | ✅ |

**Result (23 Oct):** ✅ implementation complete. The graph now follows `extract_key_facts → reconcile_corrigenda`, uses configured per-node routing and prompts with deterministic fallbacks, persists run outputs, emits node/run events and audit entries, pauses at Gate 1 with `interrupt()`, and resumes with `Command(resume=...)`. Checkpoints prefer configured Postgres, then SQLite, then memory. `make demo-cli CASE-1` materializes the checked-in fixture when needed and runs to the Gate 1 pause; the runner was also verified through a resume to completion. Phase 4 does not auto-approve a recommendation. The exact 77.34 demo score remains owned by the Phase 2 gold-factor fixture and will be asserted when the Phase 3 retrieval-backed evidence is connected.
**Review fixes (23 Oct, [S]):** running the "done when" check found that CASE-1 returned **10.0 `NO_BID`** with all 237 requirements `needs_human`. Root causes and fixes:
- **No rule was ever applied:** nothing created `parsed_rule`. Added `agents/prequalification.py`: the PQ table (PQ-01..PQ-12) plus clause 2.1.2 become the 13 hard gates, each routed by content to a Phase 2 rule tool; thresholds, windows and dates come from the tender text and key facts.
- **Key facts were empty offline.** Added `agents/key_facts.py`: deterministic, sourced extraction (deadline, pre-bid, opening, EMD, PBG, payment days, SLA cap, turnover thresholds, evaluation method); the LLM only fills gaps.
- **Every unchecked requirement became an "escalate/review" risk** (237 risks → commercial score 0). Added `agents/commercial_terms.py`: the risk register is the 9 contract clauses compared with `risk_positions` (v1 = 50, v2 = 65, as in the gold set).
- **Demo CLI used `extracted/tender_sections.json`** (the parser reference, including the corrigendum) as v1 input and labelled every file `main_rfp`. It now seeds facts, ingests the KB and uploads the four v1 files through the real pipeline.
- **Graph forked** `extract_key_facts` into both `reconcile_corrigenda` and `route_requirements`; now sequential (D4).
- **Task 4.1 was not implemented** (`routing.py` unchanged): the loader now reads the plan's `routing` section (Gemini 3 Flash for planning/drafting, GPT-OSS 120B for judging/verification), stays offline in `fake:` mode.
- **Gate 1 could not survive a restart by default** (memory checkpointer): the default checkpointer is now the app database (Postgres) or `storage/checkpoints.sqlite`. Stored `thread_id` now matches the checkpoint thread.
- Scoring inputs that are not in the tender (strategic fit 85, technical estimate 72.52, delivery 85) live in `agents/analysis_inputs.json`, labelled as demo estimates.

**Result after fixes:** `dev.py demo-cli CASE-1` from an empty database → **77.34 `BID_WITH_CONDITIONS`** in ~15 s: all 5 factors, all 13 hard-gate verdicts and the 9-clause risk register match `eligibility_gold.json`; conditions are the CEO liability approval, the bid-specific MAF and the office undertaking. Gate 1 resumes in a new process from the durable checkpoint. `tests/integration/test_phase4_graph.py` (9 tests).
**Meanwhile [S]:** scaffold the FastAPI router files against `docs/api_contract.md` with stubbed responses (no business logic).

### Phase 5 · [S] API for the v1 lifecycle

| # | Task | Status |
|---|---|---|
| 5.1 | `backend/app/main.py`: app factory, lifespan (logging, tracing, tables), CORS, contract-shaped errors (`api/errors.py`), `/health`, `/ready`, `/settings`, docs at `/docs` | ✅ |
| 5.2 | KB routes (`api/kb.py`): status, documents (role-filtered), facts (risk positions approver-only), search (role-filtered), ingest (admin, background) | ✅ |
| 5.3 | Tender routes (`api/tenders.py`): create/list/get (`TenderView`), files (corrigendum refused), ingestion, page text + download (evidence viewer), run (409 unless ingestion ready), runs, SSE events (replay after `after_id`, then live; `follow=false`; `format=json` fallback), requirements (filters), key facts, compliance, risks, assessment, audit, guardrails | ✅ |
| 5.4 | `POST /tenders/{id}/decision`: Gate 1 via `services/tender_service.decide_gate1`: approver role only (refusal audited even though the request rolls back), bound to the current version (409 otherwise), resumes the paused run; `defer` keeps it paused | ✅ |
| 5.5 | Export routes (`api/exports.py`: list, generate, download on demand) and ops routes (`api/ops.py`: metrics, guardrails, runs, cancel) | ✅ |
| 5.6 | `tests/integration/test_phase5_api.py` (14 tests) drives upload → ingestion → analyze → Gate 1 → exports over HTTP with fake LLMs; `dev.py api` (`make api`) | ✅ |

**Done when:** a script drives the full v1 flow over HTTP, and an analyst gets 403 plus an audit entry at Gate 1.
**Result (23 Oct):** ✅ done. Over HTTP: the v1 upload becomes `ready_for_analysis`, `POST /run` reaches Gate 1 with **77.34 `BID_WITH_CONDITIONS`** (13 hard gates, 9 risks), an analyst's decision gets **403 + a `gate1.denied` audit entry**, a decision for the wrong version gets 409, the bid manager's approval resumes the run to `completed` and the tender to `bid_approved`, and the compliance XLSX and ICS download. Verified on SQLite and Postgres, and with the real server (`dev.py api`) against the Postgres dev DB. Notes for Phase 6/7: amendment routes (`/amendments`, `/reanalyse`, `/versions`, `/compare`) are not built yet; `tender_view()` already exposes `amendmentPending` from tender status; `decide_gate1` rejects decisions for non-current versions, so a confirmed amendment that bumps `current_version` supersedes any pending v1 decision.
**Meanwhile [H]:** design the amendment dependency map (which check keys each change type invalidates) against `corrigendum_diff_gold.json`.

### Phase 6 · [H] Corrigendum, versioning and incremental re-analysis

| # | Task | Status |
|---|---|---|
| 6.1 | `ingestion/corrigendum_parser.py` reads Part A (existing → amended) and Part B (pre-bid response) tables; `tools/amendment_diff.py` builds typed changes (kind, field, normalised old/new values, invalidated checks), `apply_changes_to_key_facts`, section-diff fallback | ✅ |
| 6.2 | `services/amendment_service.py`: upload → `process_amendment` (own sessions, background-safe) → preview → confirm → new effective version; supersedes **every** live base-version Gate 1 review; stale drafts; exact counts | ✅ |
| 6.3 | Impact re-analysis: `reconcile_corrigenda` applies amended key facts (cited to the corrigendum) and the invalidated checks; unaffected hard gates are reused from v1 (`reused_from_version`); consortium rule C1-05 applied to similar work | ✅ |
| 6.4 | `compare_versions` / `services.amendment_service.compare_tender_versions`: score, recommendation, changed verdicts (not whole records), changed risk levels, amendments | ✅ |
| 6.5 | `tests/integration/test_phase6_corrigendum.py` (12 tests): 14/14 gold changes; CASE-2 → 78.80 `NO_BID`; v2 gates and risk register match gold; amended dates cite the corrigendum; only affected checks re-run; v1 approval superseded; KB not re-embedded | ✅ |

**Done when:** the same tender shows v1 77.34 `BID_WITH_CONDITIONS` and v2 78.80 `NO_BID` with the ISO evidence, and the v1 approval reads `superseded`.
**Review fixes (23 Oct, [S]):** CASE-2 returned **77.34 `BID_WITH_CONDITIONS`** (identical to v1) and task 6.5 was open. Causes: the diff matched sections by `section_id`, so every corrigendum section was just "added" and the 13 amendments were never extracted; and amendments were never applied to the analysis (the v1 deadline from the notice won, so ISO stayed valid). Also fixed: only *approved* Gate 1 reviews were superseded; superseded/stale counts came from the session identity map; preview processed the file inside the request transaction; `compare_versions` compared whole records (every requirement showed as changed).
**Result after fixes:** `dev.py demo-cli CASE-2` from an empty database → v1 77.34, then Corrigendum No. 1 → **78.80 `NO_BID`**: PQ-06 fails with "ISO27001 (CERT-002) expires 2026-11-10, 10 day(s) before the bid submission deadline (2026-11-20)"; eligibility 89.62 and commercial 65 match gold; PQ-01/05/06/12 re-run, the other 9 hard gates reused from v1. Typed diff: all 14 gold changes match (kind, field, old/new); 8 further binding pre-bid clarifications are listed for the reviewer (the gold set only labels PB-09).
**Meanwhile [S]:** build static UI layouts (shell, dashboard, workspace tabs) with mock data from the contract types.

### Phase 7 · [S] Frontend core + amendment and version routes

| # | Task | Status |
|---|---|---|
| 7.1 | `api/amendments.py`: upload (202, processed in the background), list, diff (409 while parsing), confirm (Bid Manager/Admin; refusals audited), reanalyse (`mode: impact|full_analysis`), versions, compare; `tests/integration/test_phase7_amendment_api.py` | ✅ |
| 7.2 | `frontend/`: Next.js 15 app shell, synthetic-data notice, role switcher (Bid Manager / Analyst → `X-User`/`X-Role`), dashboard (KB status, expiring certificates, tender cards) | ✅ |
| 7.3 | `tenders/new`: create + multi-file upload, per-file status and detail; Analyze enabled only when every file is indexed | ✅ |
| 7.4 | `tenders/[id]` workspace: live node strip (SSE with polling fallback), requirements matrix (hard gates / all / unchecked, search), evidence panel (tender clause + page text, rule trace, company evidence), risks, documents, activity (audit + guardrails) | ✅ |
| 7.5 | Gate 1 panel: system recommendation vs human decision, comment, version-bound; an Analyst click shows the server's 403 and the refusal appears in the audit trail | ✅ |
| 7.6 | Documents tab: corrigendum upload → typed diff (kind, field, before → after, Part A/B, page, checks to re-run) → confirm → re-analyse impact; Versions tab: v1/v2 cards and the comparison (changed hard gates, changed contract terms) | ✅ |

**Done when:** the v1 → Gate 1 → corrigendum → v2 `NO_BID` story runs in a clean browser with no console actions; `Makefile`: `web`.
**Result (23 Oct):** driven end to end in headless Chrome against a fresh database: upload 4 files → indexed → Analyze → 77.34 `BID_WITH_CONDITIONS`; Analyst approve → 403 shown and `gate1.denied` audited; Bid Manager approves; corrigendum → 22 typed changes (14 gold + 8 pre-bid clarifications) → confirm (v1 approval `superseded`) → re-analyse → **78.80 `NO_BID`**, REQ-PQ-06 `meets → gap`, PBG/payment/SLA cap `review → within_policy`, 9 hard gates marked `reused v1`. `dev.py web` starts the UI (runs `npm ci` on first use); `dev.py web-check` typechecks and builds it; `doctor` reports Node.js.
**Meanwhile [H]:** prepare the eval harness inputs and the injection/claim test fixtures list.

### Phase 8 · [H] Trust layer: guardrails, claim verifier, evals, measured run

| # | Task | Status |
|---|---|---|
| 8.1 | Injection screen in both ingest pipelines (visible text, hidden text, PDF metadata); quarantined spans recorded as guardrail events. Prompt Guard 2 not wired (heuristics only) | ✅ |
| 8.2 | `guardrails/tool_allowlist.py`, `policy_enforcer.py`; the hard-gate invariant (any failed gate means NO_BID) is enforced in `bid_score`. The allowlist is a policy table for future tool-calling nodes (no node calls tools by name yet) | 🟡 |
| 8.3 | `guardrails/claim_verifier.py` + `citation_verifier.py`: deterministic checks only (citation, negation/expiry, values incl. spelled-out counts, unsupported qualifiers, overlap, exception clauses); never reads expected labels. Optional semantic model not wired | 🟡 |
| 8.4 | LangSmith: optional, one redacting client for manual and automatic runs; `analysis_run -> graph -> node -> tool / retriever / LLM`; Gate 1 resume in the same thread; ingestion, amendments, Gate 1 decision, scoring, guardrails and evals traced; `tests/integration/test_phase8_tracing.py` | ✅ |
| 8.5 | `evals/run_evals.py` + `evaluators.py`: real pipeline on a fresh DB, gold matching rules, retrieval recall@6/MRR, real trap PDFs, claims; `make evals` writes `storage/evals/report.json` | ✅ |
| 8.6 | Measured offline TDR-001 run (time, LLM calls, cost; unpriced calls reported, never counted as $0) | ✅ |
| 8.7 | mypy-clean `guardrails/injection.py` | ✅ |

**Done when:** `injection_test.pdf` is quarantined, invented credentials are caught, and a measured mandatory-recall number, time and cost exist.
**Review fixes (24 Oct, [S]):** the harness read whichever `TDR-001` was in the dev database (0% recall on a fresh machine, 61.9% on another), matched by coincidental requirement IDs, ignored page/file, mixed v2 items into v1, and counted flags instead of traps; the claim verifier returned the gold label as its verdict. True recall measured with the gold rule was 57.6% (v1) / 42.9% (v2): the extractor split clauses at every PDF line wrap, table cells lost their spaces, and table-only requirements were never extracted. Also fixed: PDF-metadata injection not flagged; `.env` API keys never reached the SDKs; vectors from a previous embedder silently compared; KB permission changes ignored; runs orphaned by a restart blocked their tender; a double-clicked Gate 1 resumed twice; usage lost across the resume; formula injection in the compliance XLSX; PDF active content hidden past 1 MB or in object streams; routing to a provider without a key; non-gate requirements had no evidence (decisions D24-D28).
**Measured (24 Oct, `dev.py evals`, offline: hash embeddings, fake LLMs):** mandatory recall **100%** (v1 85/85, v2 89/89 over all gold items; live subset 33/33 and 35/35), all-item recall 98.9%, mandatory-flag accuracy 96%, precision 25-27% (many extra candidates; the gold set is not exhaustive). Assessments 77.34 `BID_WITH_CONDITIONS` and 78.80 `NO_BID` reproduced. Retrieval recall@6 0.95, MRR 0.68 (tender 0.50, company 0.85). Injection traps 4/4. Claims: 6/6 bad claims struck, 6 of 9 good claims also struck (no semantic model; several fixture spans do not contain the claimed fact). Time: KB + v1 ingest 13.4 s, v1 analysis 2.9 s, corrigendum 1.7 s, v2 impact analysis 2.9 s; 0 LLM calls, $0.
**Meanwhile [S]:** draft the deck and README sections that need the measured numbers.

### Phase 9 · [S] KB and AgentOps pages, export tests, README, deck

| # | Task | Status |
|---|---|---|
| 9.1 | Knowledge Base page (`/kb`): document and fact counts, expired/expiring credentials, documents filtered by role, facts tables (financials, certificates, projects, people with masked names, risk positions for bid managers only), hybrid search | ✅ |
| 9.2 | AgentOps page (`/ops`): runs, analysis time, LLM calls/tokens/cost (unpriced calls flagged), per-model usage, per-node latency, eval scorecard, guardrail events, LangSmith link; API `/ops/summary`, `/ops/evals` | ✅ |
| 9.3 | `tests/integration/test_phase9_exports.py`: every export opens in its reader (openpyxl, python-docx, ics, json) and shows the tender version and readable citations (filenames, not internal ids) | ✅ |
| 9.4 | README pass; `make demo` (`dev.py demo`: tables, facts, KB, then API + UI); fresh-clone setup test | ✅ |
| 9.5 | ~6-slide deck | ⏸ deferred (code first) |
| 9.6 | mypy-clean exports (no `type: ignore` left in `compliance_xlsx.py`) | ✅ |

**Done when:** a fresh clone runs with the README alone, and the deck is ready before the 15:00 review.
**Result (24 Oct):** KB and AgentOps pages verified in a browser (role switching hides 20 restricted documents and the risk positions from analysts). Export review fix: citations named tender documents by internal id (`DOC-581F96DAA0 p.4`); they now read `main_rfp.pdf p.4`. AgentOps fix: `/ops/metrics` looked for eval results in `evals/results/`, where nothing is written, so eval scores never appeared.
**Meanwhile [H]:** rehearse the 5-minute demo on the real app; note rough edges.

### Phase 10 · [H] *Stretch:* cited drafting and Gate 2 backend

| # | Task | Status |
|---|---|---|
| 10.1 | `plan_response` + `write_sections` with the routed Gemini 3 Flash model over approved KB chunks (one section: Format T-1 §2/§4); deterministic offline fallback remains available | ✅ |
| 10.2 | Verifier on the draft (Phase 8), `rewrite_failed` loop (max 2), Gate 2 `interrupt()` per section, persisted review and resume | ✅ |
| 10.3 | Draft DOCX through the export service after Gate 2 approval | ✅ |

**Done when:** after Gate 1 approval one cited section passes verification and waits at Gate 2.
**Result:** ✅ implemented. Drafting is explicitly requested after Gate 1, is version-bound, stores citations and verifier reports, pauses per section at Gate 2, and resumes after approval. Existing analysis runs remain unchanged when drafting is not requested. `draft_docx` is emitted only for approved drafts.

**Phase 10 configuration:** keep the default `LLM_FAST=fake:fast` and `LLM_STRONG=fake:strong` for offline deterministic drafting, or configure the routed `write_sections` model in `demo_data/demo_config/llm_routing_and_budget.json`. For Gemini, set `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) and select the configured Gemini model. The database/checkpointer and company KB must already be configured as described in Phases 1 and 3. LangSmith remains optional; set `LANGSMITH_TRACING=true` and its API/project variables only when tracing is required.

### Phase 11 · [S] *Stretch:* draft review UI and routes

| # | Task | Status |
|---|---|---|
| 11.1 | Routes: `GET /tenders/{id}/drafts`, `POST /drafts/{id}/review` (approve: `bid_manager` only), DOCX export | ⬜ |
| 11.2 | Draft review split view: draft left, cited source right; approve / edit / reject | ⬜ |

**Done when:** a section is approved at Gate 2 in the UI and downloads as DOCX.

### Phase 12 · [H] Demo script, fallback, final evals and video

| # | Task | Status |
|---|---|---|
| 12.1 | 5-minute demo script (rehearse to 4:30) and Q&A answers | ⬜ |
| 12.2 | Labelled replay fallback for quota/network failure | ⬜ |
| 12.3 | Final eval run; secret scan | ⬜ |
| 12.4 | Final demo video from the real app | ⬜ |

### Final freeze checklist (both, 17:30 on 24 Oct)

- [ ] Last changes merged into `main`; own freeze at 17:30.
- [ ] Commit SHA copied; repo opens from a logged-out browser.
- [ ] Repo link, SHA, PPTX and video uploaded by 17:50; confirmation screenshotted.
- [ ] No commits after 18:00 until judging ends (including 27 Oct).

## Schedule (23 – 24 Oct)

Prebuilding is permitted from 23 Oct (organiser email). Official freeze:
**24 Oct, 18:00 IST**; our own freeze is **17:30**.

| When | Phases |
|---|---|
| 23 Oct, evening → night | 1 [S] → 2 [H] → 3 [S] → 4 [H] |
| 23 Oct night → 24 Oct 08:00 | 5 [S] → 6 [H] (CASE-1 and CASE-2 green from the CLI and API) |
| 24 Oct, 08:00–11:00 | Registration and inauguration; finish Phase 6 if needed, rehearse |
| 24 Oct, 11:00–15:00 | 7 [S] → 8 [H] (video safety copy by 14:30) → 9 [S] |
| 24 Oct, from 15:00 | Team review (15 min: 5 PPT · 5 demo · 5 Q&A); note reviewers' questions |
| After review → 17:15 | Fix what the review exposed; 10 [H] → 11 [S] only if everything is green; 12 [H] |
| 17:30 | Final freeze checklist |

The full sequence is a lot for one night; if a phase overruns, cut from its
optional tasks first and keep the critical path intact. If selected,
**both members pitch in person on 27 Oct**; code stays frozen.

## Repository layout

```text
TenderBridge/
├── README.md · .env.example · pyproject.toml · uv.lock · alembic.ini · .python-version · .gitattributes
├── dev.py (cross-platform commands) · Makefile (wrapper) · docker-compose.yml (local Postgres + pgvector)
├── docs/                        # api_contract.md (routes) · interfaces.md · decisions.md (D1-D28)
├── demo_data/                   # read-only fixtures and gold files (see demo_data/README.md)
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app; startup recovers runs interrupted by a restart
│   │   ├── core/                # config (+ .env secrets export), errors, logging, security (roles)
│   │   ├── db/                  # engine, models, repositories, Alembic migrations
│   │   ├── schemas/             # Pydantic contracts
│   │   ├── ingestion/           # pdf/docx/xlsx parsers, OCR, sectionizer, upload_service, kb_ingest, corrigendum_parser
│   │   ├── knowledge/           # kb_seed (structured facts), freshness (expiring credentials)
│   │   ├── retrieval/           # chunker, embeddings (hash | bge-m3), indexer, BM25 + vector, hybrid (RRF), reranker
│   │   ├── tools/               # deterministic rules (financial, certificate, project, personnel, registration,
│   │   │                        #   commercial), bid_scoring, amendment_diff, tender/company search
│   │   ├── llm/                 # factory (structured calls + heuristic fallback), routing, budget, prompts/
│   │   ├── agents/              # graph, nodes/, prequalification (hard gates), key_facts, commercial_terms,
│   │   │                        #   runner (background runs, Gate 1 resume), checkpoint, persistence, subgraphs/
│   │   ├── guardrails/          # file_security, injection, pii, claim/citation verifiers, policy, tool allowlist
│   │   ├── services/            # tender_service (Gate 1), amendment_service (corrigenda, versions, compare)
│   │   ├── exports/             # compliance/eligibility XLSX, draft/no-bid DOCX, ICS, audit JSON, citations
│   │   ├── evals/               # run_evals (dev.py evals), evaluators (gold matching rules)
│   │   ├── ops/                 # events (SSE), audit, metrics (AgentOps), langsmith (tracing + redaction)
│   │   └── api/                 # tenders, amendments, kb, exports, ops, health routers
│   ├── scripts/                 # init_db, seed_company_facts, ingest_company_kb, run_demo_case, reembed
│   └── tests/                   # unit/ and integration/ (one file per phase)
├── evals/                       # early package skeleton (the harness lives in backend/app/evals)
├── frontend/                    # Next.js 15: dashboard, new tender, tender workspace, knowledge base, AgentOps
└── storage/                     # generated at runtime, git-ignored (uploads, parsed text, exports, eval report)
```

## Setup

Works the same on **macOS, Linux and Windows**. Every command is in `dev.py`
and needs only uv; `make <target>` is a shortcut for the same thing on
macOS/Linux.

### What you need

| Tool | Needed for | Install |
|---|---|---|
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | everything (installs Python 3.13 itself, pinned in `.python-version`) | macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh` · Windows: `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| Git | cloning | |
| Docker Desktop | only for Postgres (SQLite needs nothing) | docker.com |
| Node.js 20+ (`frontend/.nvmrc`) | only for the web UI | nodejs.org |
| Tesseract OCR | reading scanned tender pages (e.g. annexures p.12); without it they index as empty and one test skips | macOS: `brew install tesseract` · Ubuntu: `sudo apt install tesseract-ocr` · Windows: [UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki), add its folder to PATH |

Optional: provider API keys for real LLM runs, a LangSmith key for tracing, a hosted Postgres.

### First run on a new laptop

```bash
git clone https://github.com/harshbhushan21/TenderBridge.git
cd TenderBridge
uv run python dev.py setup     # installs deps into .venv, creates .env (SQLite + fake LLMs, no keys)
uv run python dev.py doctor    # checks Python, deps, Node, Tesseract, demo-data hashes, .env, database
uv run python dev.py ingest-kb # creates tables, seeds company facts, indexes the 52 KB documents (idempotent)
uv run python dev.py test      # 130 tests on a throwaway SQLite database
uv run python dev.py demo      # API + web UI together: open http://localhost:3000 (Ctrl+C stops both)
```

On macOS/Linux the same is `make setup doctor ingest-kb test demo`.
`uv run python dev.py help` lists every command.

### Optional: Postgres 16 + pgvector (Docker)

```bash
uv run python dev.py db-up     # starts the container on localhost:5433
# edit .env: comment out the SQLite DATABASE_URL / CHECKPOINT_URL lines and
#            uncomment the Postgres ones
uv run python dev.py migrate   # Alembic baseline (pgvector extension + full-text indexes)
uv run python dev.py seed
uv run python dev.py test-pg   # tests on a separate tenderbridge_test database
```

Data lives in the Docker volume `tenderbridge_tenderbridge_pgdata` (kept by
`db-down`; removed only by `docker compose down -v`). Uploaded files, parsed
text and exports go to `storage/` (git-ignored). If port 5433 is taken, set
`POSTGRES_PORT` in `.env` and use the same port in `DATABASE_URL`.

### Optional: local embeddings with BGE-M3

The default `EMBEDDING_PROVIDER=hash` needs no download. For semantic search, BAAI/bge-m3 runs
**locally** through sentence-transformers (no API key; Apple GPU/CUDA used when available); the first
use downloads about 2.3 GB from Hugging Face.

```bash
# .env: EMBEDDING_PROVIDER=huggingface:BAAI/bge-m3   (EMBEDDING_DIM stays 1024)
uv run python dev.py reembed --dry-run   # how many stored vectors came from another embedder
uv run python dev.py reembed             # regenerate them in place (text, ids and permissions untouched)
```

Search ignores vectors from a different embedder until they are regenerated, so switching back
(`hash` + `reembed`) is safe. Measured on the 40 gold questions: tender recall@6 1.00 (hash 0.95),
company recall@6 0.85 (hash 0.95); hard gates and scores are unchanged.

### Optional: shared cloud database (Supabase)

Both laptops can share one Postgres (Supabase free plan: 500 MB, pauses after 7 idle days; this
project uses about 20 MB). In the Supabase dashboard: create a project with the Data API **off**
and automatic RLS **on**, run `create extension if not exists vector with schema public;`, and copy
the **Session pooler** URI (IPv4; the transaction pooler breaks prepared statements). Then in `.env`:

```bash
DATABASE_URL=postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
CHECKPOINT_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

Copy existing local data with `pg_dump -Fc --no-owner --no-privileges -n public` and `pg_restore
--no-owner --no-privileges` (a single "schema public already exists" error is expected), or start
empty with `dev.py migrate` and `dev.py ingest-kb`. Share the URL privately (never commit `.env`);
both laptops need the same `EMBEDDING_PROVIDER`; never run `reset-db` against the shared database.
Uploaded files stay on the laptop that uploaded them, so the page viewer and downloads of another
laptop's uploads are not available.

### Running the app

```bash
uv run python dev.py demo     # both servers (make demo)
uv run python dev.py api      # or separately: API on :8000 (make api)
uv run python dev.py web      # UI on :3000, installs frontend packages on first run (make web)
```

UI at <http://localhost:3000> (dashboard, new tender, tender workspace, Knowledge base, AgentOps),
API at <http://localhost:8000> (interactive docs at `/docs`).

### Why it is portable

- `.env` is per machine and git-ignored; `.env.example` holds safe defaults, and the app runs with no `.env` at all.
- Relative paths in `DATABASE_URL`, `DEMO_DATA_DIR` and `STORAGE_DIR` resolve from the project root, never the current folder.
- `uv.lock` pins every dependency for all platforms; `.python-version` pins Python 3.13.
- `.gitattributes` keeps source files LF and leaves `demo_data/` bytes untouched, so the manifests' SHA-256 hashes still match after a Windows clone (`dev.py doctor` checks this).
- Docker names (`tenderbridge-db`, the volume) are fixed by `name:` in `docker-compose.yml`, whatever the clone folder is called.
- Optional system libraries (libmagic, Tesseract, Docling) fall back gracefully when missing.

## Configuration

Copy `.env.example` to `.env`. Environment variables override the JSON demo config.

| Variable | Default | Purpose |
|---|---|---|
| `DEMO_DATA_DIR` / `STORAGE_DIR` | `demo_data` / `storage` | Read-only fixtures / writable runtime files |
| `DATABASE_URL` | `sqlite:///storage/tenderbridge.db` | SQLite locally; `postgresql+psycopg://tenderbridge:tenderbridge@localhost:5433/tenderbridge` with `make db-up` |
| `TEST_DATABASE_URL` | empty | Postgres database for tests (`make test-pg` sets it); tests never touch `DATABASE_URL` |
| `CHECKPOINT_URL` | empty | LangGraph checkpoint store (empty → SQLite/memory) |
| `LLM_FAST` / `LLM_STRONG` | `fake:fast` / `fake:strong` | `provider:model`; see below |
| `GROQ_API_KEY` / `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) | empty | Provider keys (never commit); a node planned for a provider without a key uses `LLM_FAST`/`LLM_STRONG` |
| `EMBEDDING_PROVIDER` / `EMBEDDING_DIM` | `hash` / `1024` | Offline hash embedder, or `huggingface:BAAI/bge-m3` (local; run `dev.py reembed` after switching) |
| `HF_TOKEN` | empty | Optional: faster Hugging Face model downloads |
| `RERANKER` | `none` | Optional `bge-reranker-v2-m3` |
| `LANGSMITH_TRACING` / `LANGSMITH_PROJECT` / `LANGSMITH_API_KEY` | `false` / `tenderbridge` / empty | Optional tracing; every run is redacted (emails, phones, PAN/Aadhaar, keys; restricted KB text withheld) |
| `MAX_COST_USD` / `MAX_LLM_CALLS` / `MAX_RETRIES` / `MAX_REWRITES` / `MAX_PARALLEL_LLM` | 5 / 400 / 1 / 2 / 4 | Per-run budget and loop limits |
| `DEMO_MODE` / `ANALYSIS_MODE` | `true` / `focused` | Demo disclosures; `focused` = 42-item live subset, `full` = offline |
| `DEFAULT_COMPANY_ID` | `NIMBUS-001` | Company workspace (matches `structured_facts/company.json`) |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed browser origins |
| `MAX_UPLOAD_MB` / `MAX_ZIP_ENTRIES` / `MAX_ZIP_UNCOMPRESSED_MB` | 50 / 200 / 300 | Upload limits |
| `TB_USE_DOCLING` | `0` | Enable Docling once installed and validated |

### Models

Routing follows `demo_data/demo_config/llm_routing_and_budget.json` (free-tier
quotas from the team's Groq and Google accounts; verify model IDs with each
provider's model list before relying on them):

| Use | Model (`provider:model`) |
|---|---|
| Fast tier: extraction, key facts, corrigenda, routing | `groq:openai/gpt-oss-20b` |
| Strong tier: similar-work judge, technical grading, claim verification | `groq:openai/gpt-oss-120b` |
| Response planning and the one drafted section | `google_genai:gemini-3-flash` (20 requests/day: keep ≥5 for the live demo) |
| Injection screening | `groq:meta-llama/llama-prompt-guard-2-86m` |
| Never an LLM | arithmetic, dates, hard gates, weighted score, citation validity, exports |

Groq's 8K tokens/minute limit is the main throughput constraint: batch
sections, cap parallelism, cache by content hash, and label replayed runs.

### Roles

The data pack tags every KB document with `allowed_roles`. The app uses:

| Role | Can read | Can do |
|---|---|---|
| `analyst` | docs tagged `analyst` | upload, analyze, view; **cannot** decide Gate 1 or approve Gate 2 |
| `writer` | docs tagged `writer` / `analyst` | edit drafts, request changes |
| `bid_manager` | every KB doc | everything above + Gate 1 decision, Gate 2 approval, confirm amendments |
| `admin` | everything | KB ingestion, settings |

`hr`, `finance` and `legal` are data scopes, not login roles; only
`bid_manager` and `admin` read them. Identity comes from demo headers
(`X-User`, `X-Role`); production would use real authentication.

## Demo data and expected results

See [`demo_data/README.md`](demo_data/README.md) for provenance and every file.

| Case | Action | Expected |
|---|---|---|
| CASE-1 | Upload v1 (notice, RFP, annexures, BoQ) and analyze | `BID_WITH_CONDITIONS`, **77.34**: MSE turnover (₹52 Cr vs ₹45 Cr) and PQ-05 branch (b) pass; ISO valid on 6 Nov; CEO liability approval and OEM MAF pending |
| CASE-2 | Add + confirm Corrigendum No. 1, re-analyse | `NO_BID`, **78.80**: deadline 20 Nov, ISO expires 10 Nov, hard gate fails |
| CASE-3 | Preview/confirm the amendment | 14 typed changes; direct amendments shown apart from derived ISO impact; only affected checks re-run |
| CASE-4 | Inspect PQ-05 | Branch (b) passes; PRJ-005 `needs_human`; certified eligible value, not total value |
| CASE-5 | Isolated injection annex + flawed draft | Injection quarantined; 6 claims struck, 1 conditional |
| X1 (optional) | Synthetic Corrigendum No. 2 | `NO_BID`: MSE relaxation withdrawn, turnover also fails |

Rules: the corrigendum stays on disk and is uploaded only in the v2 step;
`structured_facts/` seeds SQL and is never embedded; `evaluation/` is
evaluator-only; `extracted/tender_sections.json` is a parser test reference.

The live demo is a **focused analysis**: 42 of 105 gold requirements (40 of 96
mandatory). Mandatory recall ≥ 95% is a **target** until we measure it.

## Testing and evaluation

```bash
uv run python dev.py test        # SQLite            (make test); extra args go to pytest, e.g. -rs -k name
uv run python dev.py test-pg     # Postgres + pgvector (make test-pg)
uv run python dev.py lint        # (make lint)
uv run python dev.py typecheck   # (make typecheck)
uv run python dev.py evals       # pipeline on TDR-001 in a fresh DB, scored against the gold files
uv run python dev.py web-check   # frontend typecheck + production build
```

Key acceptance checks: idempotent seed and KB ingest · isolated, role-filtered
retrieval · parser page fidelity · MSE turnover · PQ-05 OR logic and traps ·
ISO valid v1 / expired v2 · exact v1/v2 score and verdict · version-bound
approvals and stale drafts · unsupported-claim detection · injection
quarantine · exports open · SSE reconnect and checkpoint resume · budget stop
and labelled replay · gold files never in agent context.

## Security and data handling

- Every uploaded byte and document sentence is untrusted; suspicious spans are quarantined and surfaced, never obeyed.
- Validate extension, MIME, size, archive limits, path traversal and duplicate hashes.
- Enforce `allowed_roles`, sensitivity and `approved_for_reuse` inside retrieval, before ranking.
- Mask personal data before external model calls and LangSmith traces.
- Verify every number, date, certificate, client, SLA and personnel claim against facts and cited spans.
- Unknown mandatory eligibility blocks or goes to human review; it never silently passes.
- Bound retries, recursion, concurrency, tokens, cost and outbound actions.
- Keep `.env`, keys, `storage/`, uploads, exports and caches out of Git; run a secret scan before the final push.
- Audit every run, approval, amendment, model, prompt version, citation, cost and export.

## Working together

- One phase at a time, owned by one person. The owner works on a branch per phase or per task, e.g. `s/p3-kb-ingest`, `h/p4-gate1`, `fix/<short-name>`, and merges into `main` when the phase's **Done when** check passes. The next owner starts from that `main`. Branching and pushing will be set up later; for now work stays local.
- The person who is not building reviews and tests the previous phase and does the **Meanwhile** prep; bugs found there go on a `fix/` branch by the phase's owner.
- Update the task's status in this README in the same change that implements it.
- Before merging a phase: `lint`, `test`, `test-pg`, and `typecheck` (via `dev.py` or `make`) clean for the files the phase touched; run `doctor` after pulling.
- Contracts first: schemas (`backend/app/schemas/`), ORM models and `docs/api_contract.md` are shared; extend them by adding fields with defaults, and record breaking changes in `docs/decisions.md`.
- Integration checkpoints: Phase 3 (uploaded v1 → indexed sections), Phase 4 (CLI CASE-1), Phase 5 (API v1 flow), Phase 6 (CASE-2), Phase 7 (browser click-through).

## Reference docs

- [`docs/api_contract.md`](docs/api_contract.md): REST and SSE contract.
- [`docs/interfaces.md`](docs/interfaces.md): internal module interfaces, with status.
- [`docs/decisions.md`](docs/decisions.md): design decisions and their reasons.
- [`demo_data/README.md`](demo_data/README.md): the synthetic data pack.

## Provenance

The tender, company, safety fixtures and expected results in `demo_data/` are
synthetic fixtures created for the AgentOps 2026 demonstration. Do not present
them as official government documents, real company records or measured
results. CGI facts used in the pitch come from CGI's FY2025 MD&A (SEC Form 6-K).

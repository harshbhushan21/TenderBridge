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

> **Status (23 Oct 2026):** backend foundation and demo data exist; the API,
> most of the agent graph, retrieval, amendments and the frontend are still to
> be built. The [build plan](#build-plan) below is the source of truth for
> what is done and what is next.

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
| Repositories for KB, tenders, amendments, analysis (audit is a stub → Phase 1) | 🟡 |
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
| 1.1 | Rename package `testtbridge` → `tenderbridge` in `pyproject.toml`; remove the `src/testtbridge` stub and its script entry; `uv lock` | ⬜ |
| 1.2 | Dev tools (pytest, ruff, mypy) into a dev group; add `langchain-groq`; delete or regenerate the stale `requirements.txt` | ⬜ |
| 1.3 | Align roles in `core/security.py`: `analyst / writer / bid_manager / admin`, data scopes `hr / finance / legal` (see [Roles](#roles)) | ⬜ |
| 1.4 | `knowledge/kb_seed.py`: idempotent upsert of `structured_facts/*` with evidence spans | ⬜ |
| 1.5 | `backend/scripts/init_db.py`, `seed_company_facts.py`; finish the audit repository | ⬜ |
| 1.6 | `Makefile` targets that exist so far: `setup`, `seed`, `test` (more added by later phases) | ⬜ |
| 1.7 | Alembic baseline (only for Postgres deploy; SQLite demo uses `create_all`) | ⬜ |

**Done when:** `uv sync` works on a fresh clone, seeding twice gives the same row counts, `get_financials()` returns ₹46 / 52 / 58 Cr with spans, and `role_can_read("analyst", …)` follows the data pack's tags.
**Meanwhile [H]:** write the Phase 2 test cases from `eligibility_gold.json` and `eligibility_rules_gold.json`; confirm Groq/Gemini model IDs and quotas with a tiny request.

### Phase 2 · [H] Deterministic rules and bid scoring

| # | Task | Status |
|---|---|---|
| 2.1 | Unit tests for the existing tools: lakh↔crore, dates, fiscal years, turnover (MSE), certificate validity | ⬜ |
| 2.2 | `tools/rule_parser.py`: requirement text → structured rule (`field, operator, threshold, window, aggregation, logic`), incl. MSE relaxation and "three … OR two … OR one …" | ⬜ |
| 2.3 | `tools/project_rules.py`: PQ-05 OR branches on certified eligible value, 7-year window, scope tags; PRJ-005 `needs_human`, PRJ-004 out of window, PRJ-009 not similar | ⬜ |
| 2.4 | `tools/personnel_rules.py` (HR tracker beats CV; NDS-E105 → suggest NDS-E110) and `registration_rules.py` (Udyam, OEM letter, declarations) | ⬜ |
| 2.5 | `tools/commercial_rules.py`: clause category vs `risk_positions.json` → `within_policy / review / escalate` | ⬜ |
| 2.6 | `tools/bid_scoring.py`: hard gates + weights from `bid_scoring_policy.json`; any hard-gate gap ⇒ `NO_BID` | ⬜ |
| 2.7 | Rules as a config **rule pack** (GeM/CPPP) so a second pack loads without code changes | ⬜ |

**Done when:** every case in `eligibility_gold.json` passes with the LLM off: ₹52 Cr passes ₹45 Cr and fails ₹55 Cr, PQ-05 branch (b) passes, ISO valid on 6 Nov and expired on 20 Nov, and the scorer returns 77.34 `BID_WITH_CONDITIONS` (v1) and 78.80 `NO_BID` (v2).
**Meanwhile [S]:** read the Phase 2 code, list which tools Phase 3 retrieval must feed; sketch the UI screens on paper.

### Phase 3 · [S] KB ingestion, hybrid retrieval and tender upload

| # | Task | Status |
|---|---|---|
| 3.1 | `ingestion/sectionizer.py` (numbered headings, PQ-xx clauses, tables kept whole) and `document_classifier.py` | ⬜ |
| 3.2 | `ingestion/kb_ingest.py`: one-time, hash-idempotent KB ingest driven by `company_manifest.json`; index narrative docs only | ⬜ |
| 3.3 | `retrieval/`: chunker (200–300 token children, ~1,200 parents), indexer, keyword, vector, hybrid (role filter before ranking, RRF k=60), context_pack; reranker optional | ⬜ |
| 3.4 | `knowledge/freshness.py` + `kb_status()`: counts and expiring credentials (ISO 27001 → 10 Nov 2026) | ⬜ |
| 3.5 | `ingestion/upload_service.py`: save → validate → parse → scan → section → index, per-file status, `file_status` events; reject the `corrigendum` role on the v1 path | ⬜ |
| 3.6 | `ingestion/tender_ingest.py`: `load_effective_sections(tender_id, version)`; BoQ rows | ⬜ |
| 3.7 | Tests: parser fidelity vs `extracted/tender_sections.json` and scanned page 12; 5 `retrieval_qa.json` questions; analyst cannot retrieve `bid_risk_policy.pdf`; second ingest re-embeds nothing | ⬜ |
| 3.8 | `Makefile`: `ingest-kb` | ⬜ |

**Done when:** the four v1 files ingest to `ready_for_analysis` with page-citable sections and BoQ rows, with no recommendation yet, and KB queries return the right doc and page.
**Meanwhile [H]:** write the shredder / router / similarity-judge prompts for Phase 4 and test them by hand on two sections.

### Phase 4 · [H] Agent graph to Gate 1, runner and persistence

| # | Task | Status |
|---|---|---|
| 4.1 | Routing loader reads the `routing` section of `llm_routing_and_budget.json` (per-node model, prices); Groq smoke test | ⬜ |
| 4.2 | Reorder to `extract_key_facts → reconcile_corrigenda` (decision D4) | ⬜ |
| 4.3 | Prompts in `llm/prompts/`; real LLM calls in shred / key facts / route; recall-first two-pass extraction incl. tables | ⬜ |
| 4.4 | `agents/subgraphs/requirement_router.py`: dispatch to Phase 2 tools or the RAG grader; `Send()` fan-out with a concurrency cap | ⬜ |
| 4.5 | Gate 1 as `interrupt()` + `Command(resume=…)`; checkpointer (Postgres → SQLite → memory) | ⬜ |
| 4.6 | `agents/runner.py` (background start, resume, cancel, run state) and `agents/persistence.py` (write/read results) | ⬜ |
| 4.7 | Events and audit emitted per node | ⬜ |
| 4.8 | `backend/scripts/run_demo_case.py CASE-1`; `Makefile`: `demo-cli` | ⬜ |

**Done when:** a freshly uploaded v1 runs to Gate 1 from the CLI and returns 77.34 `BID_WITH_CONDITIONS` with citations, and the paused run resumes after a restart.
**Meanwhile [S]:** scaffold the FastAPI router files against `docs/api_contract.md` with stubbed responses (no business logic).

### Phase 5 · [S] API for the v1 lifecycle

| # | Task | Status |
|---|---|---|
| 5.1 | `backend/app/main.py`: app factory, CORS, error handlers, `/health`, `/ready`, `/settings` | ⬜ |
| 5.2 | KB routes: status, documents, facts, search, ingest (admin) | ⬜ |
| 5.3 | Tender routes: create, files, ingestion, run, runs, SSE events (reconnect via `after_id`), requirements, key facts, compliance, risks, assessment | ⬜ |
| 5.4 | `POST /tenders/{id}/decision`: Gate 1, `bid_manager` only, version-checked, audited | ⬜ |
| 5.5 | Export routes (compliance/eligibility XLSX, ICS, audit JSON) and ops routes (metrics, guardrails, runs, cancel) | ⬜ |
| 5.6 | Integration test: v1 upload → analyze → Gate 1 through the API with fake LLMs; `Makefile`: `api` | ⬜ |

**Done when:** a script drives the full v1 flow over HTTP, and an analyst gets 403 plus an audit entry at Gate 1.
**Meanwhile [H]:** design the amendment dependency map (which check keys each change type invalidates) against `corrigendum_diff_gold.json`.

### Phase 6 · [H] Corrigendum, versioning and incremental re-analysis

| # | Task | Status |
|---|---|---|
| 6.1 | `tools/amendment_diff.py`: typed changes, `apply_amendments`, `invalidation_for` | ⬜ |
| 6.2 | `services/amendment_service.py`: upload → parse → diff preview → confirm → new version; supersede v1 approval; mark drafts stale | ⬜ |
| 6.3 | `agents/subgraphs/amendment_impact.py`: direct amendments vs derived impacts; reuse unaffected checks | ⬜ |
| 6.4 | Version comparison function (score, recommendation, changed items) | ⬜ |
| 6.5 | Tests: 14 changes vs `corrigendum_diff_gold.json`; `run_demo_case.py CASE-2` → 78.80 `NO_BID` without re-embedding the KB | ⬜ |

**Done when:** the same tender shows v1 77.34 `BID_WITH_CONDITIONS` and v2 78.80 `NO_BID` with the ISO evidence, and the v1 approval reads `superseded`.
**Meanwhile [S]:** build static UI layouts (shell, dashboard, workspace tabs) with mock data from the contract types.

### Phase 7 · [S] Frontend core + amendment and version routes

| # | Task | Status |
|---|---|---|
| 7.1 | Routes: amendments (upload, list, diff, confirm), reanalyse, versions, compare, audit | ⬜ |
| 7.2 | App shell, role switcher (Bid Manager / Analyst), dashboard | ⬜ |
| 7.3 | New tender + upload page with per-file status; Analyze enabled only when ready | ⬜ |
| 7.4 | Tender workspace: live node strip (SSE), requirements matrix, evidence panel (tender clause + company proof + rule trace) | ⬜ |
| 7.5 | Gate 1 panel: recommendation vs human decision, comments, audit entry | ⬜ |
| 7.6 | Amendment upload → diff preview (direct vs derived) → confirm → re-analyse → v1 vs v2 comparison | ⬜ |

**Done when:** the v1 → Gate 1 → corrigendum → v2 `NO_BID` story runs in a clean browser with no console actions; `Makefile`: `web`.
**Meanwhile [H]:** prepare the eval harness inputs and the injection/claim test fixtures list.

### Phase 8 · [H] Trust layer: guardrails, claim verifier, evals, measured run

| # | Task | Status |
|---|---|---|
| 8.1 | Injection screen in the ingest pipeline (heuristics + Prompt Guard 2); quarantined spans recorded as guardrail events | ⬜ |
| 8.2 | `guardrails/tool_allowlist.py`, `policy_enforcer.py` (hard gates, no outbound actions, version-bound decisions) | ⬜ |
| 8.3 | `guardrails/claim_verifier.py` + `citation_verifier.py` (code checks first, GPT-OSS 120B for semantic support); CASE-5 as an isolated test: 6 claims struck, 1 conditional | ⬜ |
| 8.4 | LangSmith tracing on, with PII redaction verified | ⬜ |
| 8.5 | `evals/run_evals.py` + evaluators: mandatory recall (42-item live subset), key facts, eligibility, corrigendum diff, retrieval recall@6, safety traps; `Makefile`: `evals` | ⬜ |
| 8.6 | Measured TDR-001 run: time and cost per tender for the ROI slide; record demo video safety copy | ⬜ |

**Done when:** `injection_test.pdf` is quarantined, invented credentials are caught, and a measured mandatory-recall number, time and cost exist.
**Meanwhile [S]:** draft the deck and README sections that need the measured numbers.

### Phase 9 · [S] KB and AgentOps pages, export tests, README, deck

| # | Task | Status |
|---|---|---|
| 9.1 | Knowledge Base page: doc counts, facts, expiring-certificate warning, masked PII view | ⬜ |
| 9.2 | AgentOps page: cost, latency, eval scores, guardrail events, LangSmith link | ⬜ |
| 9.3 | Export tests: every file opens and shows version and citations | ⬜ |
| 9.4 | README final pass; `make demo`; fresh-clone setup test | ⬜ |
| 9.5 | ~6-slide PPTX (cream/brown): problem → use case/pipeline → agent graph → Responsible AI (security, privacy, explainability, audit, role-based access, human approval) → measured ROI → reuse ("what stays vs what you configure") + differentiation | ⬜ |

**Done when:** a fresh clone runs with the README alone, and the deck is ready before the 15:00 review.
**Meanwhile [H]:** rehearse the 5-minute demo on the real app; note rough edges.

### Phase 10 · [H] *Stretch:* cited drafting and Gate 2 backend

| # | Task | Status |
|---|---|---|
| 10.1 | `plan_response` + `write_sections` with Gemini 3 Flash over approved KB chunks (one section: Format T-1 §2/§4) | 🟡 |
| 10.2 | Verifier on the draft (Phase 8), `rewrite_failed` loop (max 2), Gate 2 `interrupt()` per section | ⬜ |
| 10.3 | Draft DOCX through the export service | ⬜ |

**Done when:** after Gate 1 approval one cited section passes verification and waits at Gate 2.

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

`✅` exists today, `⬜` planned. Planned files are listed so each phase
knows where its code goes.

```text
TenderBridge/
├── README.md · .env.example · pyproject.toml · uv.lock · requirements.txt (stale, task 1.2)
├── Makefile ⬜ · docker-compose.yml ⬜
├── docs/
│   ├── api_contract.md ✅       # REST + SSE contract (single source for routes)
│   ├── interfaces.md ✅         # internal module contracts with status
│   └── decisions.md ✅          # design decisions log
├── demo_data/ ✅                # read-only fixtures (see demo_data/README.md)
├── backend/
│   ├── app/
│   │   ├── main.py ⬜
│   │   ├── core/ ✅             # config, errors, logging, security
│   │   ├── db/ ✅               # engine, models, repositories
│   │   ├── schemas/ ✅          # Pydantic contracts
│   │   ├── ingestion/ 🟡        # parsers ✅; sectionizer, classifier, upload_service, tender_ingest, kb_ingest ⬜
│   │   ├── knowledge/ ⬜        # kb_seed, fact_provenance, fact_validation, freshness
│   │   ├── retrieval/ 🟡        # embeddings ✅; chunker, indexer, keyword, vector, hybrid, reranker, context_pack ⬜
│   │   ├── tools/ 🟡            # dates, facts, financial, certificate, searches ✅; rule_parser, project, personnel, registration, commercial, amendment_diff, citation_lookup, boq, bid_scoring, registry ⬜
│   │   ├── llm/ 🟡              # factory, routing, budget ✅; prompts/ ⬜
│   │   ├── agents/ 🟡           # graph.py, nodes/core.py 🟡; runner, persistence, subgraphs/, ask_tender ⬜
│   │   ├── guardrails/ 🟡       # file_security, injection, pii ✅; claim/citation verifier, tool_allowlist, policy_enforcer ⬜
│   │   ├── services/ ⬜         # tender_service, amendment_service
│   │   ├── exports/ ✅          # xlsx, docx, ics, audit json, service (untested)
│   │   ├── ops/ ✅              # events, audit, metrics, langsmith
│   │   └── api/ ⬜              # routers
│   ├── scripts/ ⬜              # init_db, seed_company_facts, ingest_company_kb, run_demo_case, smoke_test
│   └── tests/ 🟡                # conftest ✅; unit / integration / e2e ⬜
├── evals/ 🟡                    # package skeleton; run_evals.py, evaluators ⬜
├── frontend/ 🟡                 # Next.js package + src/lib ✅; app pages and components ⬜
└── storage/                     # generated at runtime, git-ignored
```

## Setup

Prerequisites: Python **3.13**, [uv](https://docs.astral.sh/uv/), Node.js 20+
and npm. Optional: PostgreSQL 16 + pgvector, Tesseract (scanned pages),
provider API keys.

```bash
# backend (from the project root)
uv sync
cp .env.example .env          # SQLite + fake LLMs: no keys needed

# foundation smoke checks (until the API exists)
uv run python -c "from backend.app.core.config import get_settings; print(get_settings().demo_data_dir)"
uv run python -c "from backend.app.db.engine import init_db, check_db; init_db(); print(check_db())"
uv run pytest backend/tests -q

# after Phase 9
uv run uvicorn backend.app.main:app --reload --port 8000

# frontend (after Phase 10)
cd frontend && npm install && cp .env.local.example .env.local && npm run dev
```

UI at <http://localhost:3000>, API at <http://localhost:8000>. A one-command
`make demo` (task 9.4) will replace these steps once the targets are tested.

## Configuration

Copy `.env.example` to `.env`. Environment variables override the JSON demo config.

| Variable | Default | Purpose |
|---|---|---|
| `DEMO_DATA_DIR` / `STORAGE_DIR` | `demo_data` / `storage` | Read-only fixtures / writable runtime files |
| `DATABASE_URL` | `sqlite:///storage/tenderbridge.db` | SQLite locally; `postgresql+psycopg://…` for Postgres |
| `CHECKPOINT_URL` | empty | LangGraph checkpoint store (empty → SQLite/memory) |
| `LLM_FAST` / `LLM_STRONG` | `fake:fast` / `fake:strong` | `provider:model`; see below |
| `GROQ_API_KEY` / `GOOGLE_API_KEY` | empty | Provider keys (never commit) |
| `EMBEDDING_PROVIDER` / `EMBEDDING_DIM` | `hash` / `1024` | Offline hash embedder, or e.g. `huggingface:BAAI/bge-m3` |
| `RERANKER` | `none` | Optional `bge-reranker-v2-m3` |
| `LANGSMITH_TRACING` / `LANGSMITH_PROJECT` / `LANGSMITH_API_KEY` | `false` / `tenderbridge` / empty | Tracing (mask PII first) |
| `MAX_COST_USD` / `MAX_LLM_CALLS` / `MAX_RETRIES` / `MAX_REWRITES` / `MAX_PARALLEL_LLM` | 5 / 400 / 1 / 2 / 4 | Per-run budget and loop limits |
| `DEMO_MODE` / `ANALYSIS_MODE` | `true` / `focused` | Demo disclosures; `focused` = 42-item live subset, `full` = offline |
| `DEFAULT_COMPANY_ID` | `NIMBUS` | Company workspace |
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

Groq needs `langchain-groq` (task 1.2) and the per-node routing fix (task 4.1).
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
uv run pytest backend/tests -q
uv run ruff check backend
uv run mypy backend/app
uv run python -m evals.run_evals          # Phase 7.5
cd frontend && npm run typecheck && npm run build
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

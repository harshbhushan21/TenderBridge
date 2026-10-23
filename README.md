# TenderBridge

TenderBridge is an evidence-first bid/no-bid copilot for IT-infrastructure
tenders. It ingests a tender, extracts and classifies requirements, compares
them with a persistent company knowledge base, evaluates deterministic
eligibility and commercial rules, and presents a versioned recommendation for
human approval.

The primary demonstration uses a simulated State Data Centre operations and
maintenance tender (`TDR-001`) and the fictional Nimbus Digital Services
company. It is not an official government tender and it does not submit bids
to GeM, CPPP, or any other portal.

> **Implementation status:** the repository contains the backend foundation and
> demo data, but it is not yet a complete runnable web product. This README is
> the source of truth for what is implemented and what remains before the
> final demo/release.

## Contents

- [What is implemented](#what-is-implemented)
- [What remains](#what-remains)
- [Target user workflow](#target-user-workflow)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Local setup](#local-setup)
- [Configuration](#configuration)
- [LLM and embedding configuration](#llm-and-embedding-configuration)
- [Database configuration](#database-configuration)
- [Demo data and expected results](#demo-data-and-expected-results)
- [Security and data-handling rules](#security-and-data-handling-rules)
- [Testing and evaluation](#testing-and-evaluation)
- [API and frontend completion contract](#api-and-frontend-completion-contract)
- [Release checklist](#release-checklist)

## What is implemented

The following capabilities already have code or data in this repository:

| Area | Current state |
|---|---|
| Configuration | `backend/app/core/config.py` centralizes paths, environment variables, limits, LLM settings, storage directories, and CORS. |
| Storage model | SQLAlchemy models cover companies, KB documents/chunks, financials, certificates, projects, people, tender documents/versions/chunks, requirements, assessments, amendments, reviews, events, metrics, and audit records. |
| Database engine | SQLite works without external services. PostgreSQL plus pgvector is supported by the engine/model layer. |
| Schemas | Pydantic schemas exist for documents, requirements, eligibility, assessments, amendments, graph state, and source evidence. |
| Ingestion primitives | PDF, DOCX, XLSX, OCR, file validation, SHA-256 hashing, and document-security helpers exist. |
| Guardrails | Upload validation, suspicious-content/injection checks, PII handling, role/sensitivity metadata, and bounded processing primitives exist. |
| Deterministic rules | Date normalization, financial checks, certificate validity checks, fact access, and hard-gate/weighted-score logic exist. |
| Agent graph | A LangGraph graph exists for intake, tender loading, requirement shredding, deduplication, amendment reconciliation, fact extraction, routing, eligibility/risk evaluation, scoring, no-bid reporting, and finalization. |
| LLM abstraction | `provider:model` routing, fast/strong tiers, structured output, schema-repair retries, fake deterministic mode, usage accounting, and budget checks exist. |
| Retrieval foundation | Embedding abstraction and database chunk models exist. The default hash embedder makes local smoke tests possible without downloading a model. |
| Exports | XLSX compliance output, DOCX draft output, ICS dates, and audit JSON export modules exist. |
| Operations | Structured logging, audit/event recording, metrics, and LangSmith integration helpers exist. |
| Demo fixtures | The complete synthetic tender/company/evaluation pack exists under `demo_data/`. |
| Frontend foundation | A Next.js 15/React 19 package and typed API/event/formatting helpers exist under `frontend/src/lib/`. |

The existing code is deliberately safe in fake mode: if no real LLM is
configured, nodes must use a deterministic heuristic and mark the result as a
fallback. Arithmetic, date comparison, hard gates, weighted scoring, citation
ID validation, and exports must remain code-driven.

## What remains

These items are required for the final implementation and demo:

1. Add a FastAPI application entrypoint and routers for health/readiness,
   KB ingestion/status, tender upload/versioning, analysis, SSE progress,
   requirements/evidence, Gate 1 and Gate 2 approvals, amendment preview and
   confirmation, exports, audit, and replay.
2. Add Alembic migrations and executable database initialization/seed scripts.
3. Implement idempotent company-facts seeding and one-time KB ingestion. The
   KB must not be re-embedded for every tender.
4. Complete live PDF/DOCX/XLSX parsing, section indexing, isolated
   `tender_chunks`/`kb_chunks` retrieval, role filtering, and source-span
   citations.
5. Add the production prompts and wire structured LLM calls into the graph
   nodes that currently use conservative deterministic fallbacks.
6. Implement the full amendment/version workflow: typed diff preview,
   confirmation, dependency invalidation, incremental re-analysis, stale
   drafts, and version-bound approvals.
7. Add actual LangGraph interrupts/checkpoint resume for Gate 1 and Gate 2.
8. Complete claim verification, injection quarantine, PII masking before
   external LLM/LangSmith calls, and outbound-tool restrictions.
9. Add the frontend pages/components for dashboard, KB, tender upload,
   analysis progress, evidence viewer, requirement matrix, bid decision,
   amendment diff, version comparison, draft review, AgentOps, and settings.
10. Add unit, integration, E2E, safety, evaluation, and export tests, then
    rehearse the exact click path from a clean browser.

The current `frontend` package has no application pages yet, and
`backend/app/api/` has no route implementation. Do not advertise the
repository as a complete FastAPI/Next.js application until these are added.

## Target user workflow

1. **KB ready:** onboard Nimbus once; show document count and certificate
   expiry warnings.
2. **Create tender:** upload the original notice, RFP, annexures, and BOQ.
   Do not upload the corrigendum in this step.
3. **Validate and index:** show file-level progress. Uploading must not start
   eligibility analysis.
4. **Analyze:** run the graph and stream real node events through SSE.
5. **Inspect evidence:** show each requirement, status, source document/page,
   quote, and company evidence.
6. **Gate 1:** present the deterministic recommendation and require a human
   bid/no-bid decision with comments.
7. **Draft optionally:** generate one cited section only after bid approval;
   send it through Gate 2 review.
8. **Add amendment:** upload the corrigendum to the same tender workspace.
9. **Preview and confirm:** show direct typed changes separately from derived
   company-specific effects.
10. **Re-analyze impact:** reuse unaffected checks; rerun affected checks.
11. **Compare versions:** retain v1 history, supersede its approval when
    required, and mark its draft stale.
12. **Export:** provide XLSX/DOCX/ICS/audit JSON. Never auto-submit externally.

## Architecture

```text
Next.js UI
   | REST + SSE
FastAPI application
   | services / repositories
LangGraph analysis workflow
   |-- deterministic facts/rules (authoritative for numbers and gates)
   |-- fast LLM tier (extraction, routing, reconciliation)
   |-- strong LLM tier (technical reasoning, planning, drafting, verification)
   |-- guardrails, budgets, audit, metrics
SQLAlchemy
   |-- SQLite for local zero-setup development
   |-- PostgreSQL 16 + pgvector for shared/deployed use
   |-- isolated tender and company retrieval scopes
demo_data/ (read-only source fixtures)
storage/ (ignored, writable runtime files)
```

### Non-negotiable design rules

- Company KB is persistent and onboarded once.
- Upload and analyze are separate actions.
- Tender text and company text are separate retrieval scopes.
- SQL/fact tables are authoritative for amounts, dates, certificates,
  personnel, projects, and eligibility.
- Every fact and claim carries document ID, page, section, and text span.
- A failed mandatory gate overrides a high weighted score.
- Evaluation gold labels never enter normal retrieval or agent context.
- Documents are untrusted data; instructions inside documents are never
  system or tool instructions.
- Human approvals are version-bound and auditable.
- No agent can submit externally or write back to the company KB.

## Repository layout

```text
TenderBridge/
├── README.md
├── .env.example
├── pyproject.toml
├── requirements.txt
├── uv.lock
├── backend/
│   ├── app/
│   │   ├── agents/          # LangGraph and graph nodes
│   │   ├── core/            # settings, logging, errors, security
│   │   ├── db/              # engine, models, repositories
│   │   ├── exports/         # XLSX, DOCX, ICS, audit JSON
│   │   ├── guardrails/      # file, injection, PII controls
│   │   ├── ingestion/       # PDF, DOCX, XLSX, OCR, hashing
│   │   ├── llm/             # provider factory, routing, budgets
│   │   ├── ops/             # audit, events, metrics, LangSmith
│   │   ├── retrieval/       # embedding abstraction
│   │   ├── schemas/         # Pydantic contracts
│   │   └── tools/            # facts and deterministic rule tools
│   └── tests/
├── demo_data/
│   ├── company_kb/
│   ├── structured_facts/
│   ├── tender/TDR-001/
│   ├── evaluation/
│   └── demo_config/
├── frontend/
│   ├── package.json
│   └── src/lib/              # current typed client/event helpers
└── storage/                  # generated; keep out of source control
```

Keep `demo_data/` at the project root. The backend resolves it through
`DEMO_DATA_DIR`; never copy private KB documents into `frontend/public`.

## Prerequisites

- Python 3.13 (the `pyproject.toml` package requires `>=3.13`; the legacy
  `requirements.txt` says Python 3.11 but should not override `pyproject.toml`)
- Node.js 20 or newer and npm
- Git
- Optional for production-like local development: Docker and PostgreSQL 16
  with pgvector
- Optional for scanned PDFs: Tesseract OCR
- Optional for real model calls: an API key for the selected provider

## Local setup

### 1. Backend environment

```bash
cd "D drive/TenderBridge"
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .
cp .env.example .env
```

The checked-in `.env.example` uses SQLite and fake LLMs, so it does not need
database credentials or provider keys. The generated `storage/` directory is
the only writable runtime area.

### 2. Current foundation smoke checks

The repository currently has no FastAPI entrypoint or CLI script. Until those
are implemented, validate the foundation with:

```bash
source .venv/bin/activate
python -c "from backend.app.core.config import get_settings; print(get_settings().model_dump())"
python -c "from backend.app.db.engine import init_db, check_db; init_db(); print(check_db())"
pytest backend/tests -q
ruff check backend
```

### 3. Target backend startup

After the API entrypoint is added, the supported startup command should be:

```bash
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Required endpoints are `/health` (process health) and `/ready` (configuration,
database, storage, and required-provider readiness). A healthy process must
not be reported as ready when its database or required model configuration is
unavailable.

### 4. Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run typecheck
npm run dev
```

The UI is expected at <http://localhost:3000> and the API at
<http://localhost:8000>. The current package contains only the frontend
foundation; pages and API calls still need to be implemented.

## Configuration

Copy `.env.example` to `.env`. Environment variables take precedence over
JSON demo configuration where stated.

| Variable | Default | Purpose |
|---|---|---|
| `DEMO_DATA_DIR` | `demo_data` | Root of synthetic tender/company/evaluation fixtures. |
| `STORAGE_DIR` | `storage` | Writable uploads, parsed files, cache, exports, and replay. |
| `DATABASE_URL` | `sqlite:///storage/tenderbridge.db` | SQLite for local work; use PostgreSQL for deployment. |
| `CHECKPOINT_URL` | empty | LangGraph checkpoint store; configure PostgreSQL/SQLite when resume is enabled. |
| `LLM_FAST` | `fake:fast` | Cheap/fast model for extraction, routing, and reconciliation. |
| `LLM_STRONG` | `fake:strong` | Strong model for reasoning, drafting, and claim verification. |
| `LLM_TIMEOUT_S` | `60` | Per-call provider timeout. |
| `EMBEDDING_PROVIDER` | `hash` | `hash`, `huggingface:...`, `openai:...`, `google_genai:...`, or `ollama:...`. |
| `EMBEDDING_DIM` | `1024` | Embedding dimension; must match the database vector column. |
| `RERANKER` | `none` | Optional reranker, such as `bge-reranker-v2-m3`. |
| `LANGSMITH_TRACING` | `false` | Enable trace export only after configuring a key and PII policy. |
| `LANGSMITH_PROJECT` | `tenderbridge` | LangSmith project name. |
| `LANGSMITH_API_KEY` / `LANGCHAIN_API_KEY` | empty | LangSmith credentials; never commit them. |
| `MAX_COST_USD` | `5` | Per-run cost ceiling. |
| `MAX_LLM_CALLS` | `400` | Per-run call ceiling. |
| `MAX_RETRIES` | `1` | Structured-output repair/provider retries. |
| `MAX_REWRITES` | `2` | Maximum failed-draft rewrites. |
| `MAX_PARALLEL_LLM` | `4` | Concurrency cap to protect quotas. |
| `DEMO_MODE` | `true` | Enables synthetic/demo behavior and disclosures. |
| `ANALYSIS_MODE` | `focused` | `focused` for the live subset; `full` for offline evaluation. |
| `DEFAULT_COMPANY_ID` | `NIMBUS` | Default company workspace. |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowed browser origins. |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `false` | Application logging controls. |
| `MAX_UPLOAD_MB` | `50` | Maximum individual upload size. |
| `MAX_ZIP_ENTRIES` | `200` | Maximum archive entries if archive upload is enabled. |
| `MAX_ZIP_UNCOMPRESSED_MB` | `300` | Archive expansion limit. |
| `TB_USE_DOCLING` | `0` | Enable Docling only when installed and validated. |

Use absolute paths in deployed environments and mount `/app/demo_data`
read-only and `/app/storage` read-write.

## LLM and embedding configuration

The model factory accepts `provider:model` values:

```dotenv
# Deterministic local smoke mode
LLM_FAST=fake:fast
LLM_STRONG=fake:strong
EMBEDDING_PROVIDER=hash

# OpenAI-compatible example
LLM_FAST=openai:gpt-4o-mini
LLM_STRONG=openai:gpt-4o
OPENAI_API_KEY=replace-locally
EMBEDDING_PROVIDER=openai:text-embedding-3-small

# Google example
LLM_FAST=google_genai:gemini-2.0-flash
LLM_STRONG=google_genai:gemini-2.5-pro
GOOGLE_API_KEY=replace-locally
EMBEDDING_PROVIDER=google_genai:models/text-embedding-004

# Local Ollama example
LLM_FAST=ollama:llama3.1
LLM_STRONG=ollama:llama3.1
EMBEDDING_PROVIDER=ollama:bge-m3
```

Provider SDKs are optional at import time, but the selected provider package
and its credential must be installed/configured before a real run. Verify
model IDs against the provider's current model list; the values in
`demo_data/demo_config/llm_routing_and_budget.json` are routing guidance, not
credentials or a guarantee that those model IDs remain available.

Node routing, token budgets, and prices are configured in
`demo_data/demo_config/llm_routing_and_budget.json`. The intended routing is:

- fast model: requirement extraction, key facts, amendment reconciliation,
  routing, bid scoring, and no-bid explanation;
- strong model: similarity judgment, technical grading, response planning,
  cited writing, claim verification, and bounded rewrites;
- code only: arithmetic, dates, hard gates, weighted scoring, citation
  validation, and file exports.

Before enabling external tracing, mask PII and confirm that synthetic/demo
data is the only data leaving the deployment.

## Database configuration

### SQLite (default)

SQLite is appropriate for local development and deterministic smoke tests:

```dotenv
DATABASE_URL=sqlite:///storage/tenderbridge.db
CHECKPOINT_URL=
```

Run `init_db()` once the environment is installed. SQLite stores embeddings
as JSON and searches them in Python.

### PostgreSQL + pgvector

For shared or deployed environments:

```dotenv
DATABASE_URL=postgresql+psycopg://tenderbridge:password@localhost:5432/tenderbridge
CHECKPOINT_URL=postgresql+psycopg://tenderbridge:password@localhost:5432/tenderbridge
EMBEDDING_PROVIDER=huggingface:BAAI/bge-m3
EMBEDDING_DIM=1024
```

Create the database, enable the `vector` extension, run migrations, and then
seed facts and ingest the KB. Do not use `create_all()` as a replacement for
versioned migrations in production.

## Demo data and expected results

`demo_data/README.md` describes provenance and file-level contents. The pack
contains 52 synthetic company documents, structured facts, the TDR-001 tender,
gold evaluation labels, safety fixtures, and demo configuration.

Important data rules:

- `tender/TDR-001/original/` contains the original four upload files plus the
  corrigendum. The corrigendum must remain on disk but must be uploaded only
  in the v2 step.
- `structured_facts/` seeds SQL facts and must not be embedded as narrative
  chunks.
- `evaluation/` is evaluator-only. Gold labels and safety traps must never be
  loaded by production RAG or included in agent prompts.
- `extracted/tender_sections.json` is a parser reference fixture, not a
  silent replacement for live parsing.

Expected business outcomes:

| Case | Action | Expected result |
|---|---|---|
| CASE-1 | Upload original pack and analyze | `BID_WITH_CONDITIONS`, score `77.34`; MSE turnover path and similar-work OR branch pass; ISO valid on 2026-11-06. |
| CASE-2 | Add and confirm Corrigendum No. 1, then re-analyze | `NO_BID`, score `78.80`; deadline becomes 2026-11-20 and ISO expires 2026-11-10, so the hard gate fails despite improved commercial terms. |
| CASE-3 | Preview/confirm amendment | Typed amendment diff and affected checks; direct amendments must be separated from derived ISO impact. |
| CASE-4 | Evaluate PQ-05 | Similar-work branch (b) passes; PRJ-005 requires human judgment and total contract value must not replace certified eligible value. |
| X1 | Optional Corrigendum No. 2 | `NO_BID` because withdrawal of MSE relaxation also breaks turnover. |

The live demo is a **focused analysis**, not full-tender coverage:
105 gold requirements (96 mandatory), 42 live-subset requirements (40
mandatory), 29 key facts, 40 retrieval questions, 15 claim labels, and 52 KB
documents are provided for evaluation.

## Security and data-handling rules

- Treat every uploaded byte and every document sentence as untrusted.
- Validate extension, MIME type, size, archive entries, archive expansion,
  path traversal, and SHA-256 duplicates.
- Detect hidden/white/tiny text and instruction-like content; quarantine
  suspicious spans instead of obeying them.
- Enforce `allowed_roles`, sensitivity, and `approved_for_reuse` at retrieval
  time.
- Mask personal data before external provider calls and LangSmith traces.
- Verify every numerical, date, certificate, client, SLA, and personnel claim
  against structured facts and cited source spans.
- Unknown mandatory eligibility must block or require human review; it must
  never silently pass.
- Bound retries, recursion, concurrency, outbound actions, token usage, cost,
  and file processing.
- Keep uploads, parsed files, exports, caches, replay files, `.env`, and
  provider keys out of Git.
- Preserve audit records for analysis runs, approvals, amendments, model
  names, prompt versions, citations, costs, errors, and exports.

## Testing and evaluation

The final implementation must include:

```bash
pytest backend/tests -q
pytest backend/tests --cov=backend/app --cov-report=term-missing
ruff check backend
mypy backend/app
cd frontend && npm run typecheck && npm run build
python -m evals.run_evals
```

Required acceptance coverage:

- settings and path resolution from any working directory;
- database health and idempotent company seeding;
- upload validation and quarantine;
- parser page/section/source-span fidelity;
- isolated tender/KB retrieval with role filters;
- money conversion and date normalization;
- MSE turnover (`52 Cr` versus `45 Cr`/`55 Cr`);
- similar-work OR rules, seven-year window, eligible share, and traps;
- ISO valid for v1 and expired for v2;
- exact v1/v2 recommendation and score;
- amendment diff and safe dependency reuse;
- version-bound approvals and stale drafts;
- unsupported-claim detection;
- safety-trap isolation;
- XLSX/DOCX/ICS/audit export readability;
- SSE reconnect and checkpoint resume;
- LLM budget stop and labelled replay fallback;
- proof that evaluation gold files never reach normal agent context.

Metrics are targets until measured. In particular, mandatory requirement
recall of at least 95% is a target from the data pack, not an existing
result.

## API and frontend completion contract

The API should expose typed JSON contracts and return source evidence rather
than opaque model prose. The minimum route groups are:

| Route group | Required behavior |
|---|---|
| `/health`, `/ready` | Process and dependency checks. |
| `/companies/{id}/kb` | KB status, one-time ingestion, document counts, expiry warnings. |
| `/tenders` | Create workspace, list versions, upload original files. |
| `/tenders/{id}/documents` | Validate/upload documents and report ingestion status. |
| `/tenders/{id}/analyze` | Start analysis only when ingestion is ready. |
| `/tenders/{id}/events` | SSE node progress, errors, run IDs, and reconnect support. |
| `/tenders/{id}/requirements` | Requirement matrix with source and company evidence. |
| `/tenders/{id}/assessment` | Score, gates, risks, conditions, and recommendation. |
| `/tenders/{id}/approvals` | Gate 1/Gate 2 actions with version-bound audit records. |
| `/tenders/{id}/amendments` | Upload, preview typed diff, confirm, and re-analyze impact. |
| `/tenders/{id}/exports/*` | Compliance XLSX, risk/bid report, cited DOCX, ICS, audit JSON. |

The frontend must disable Analyze until ingestion is ready and disable
Re-analyze until an amendment is confirmed. It must distinguish the system
recommendation from a human approval and show the effective tender version
everywhere.

Frontend configuration belongs in `frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_BASE=http://localhost:8000
NEXT_PUBLIC_DEMO_USER=bid.manager@nimbus.example
NEXT_PUBLIC_DEMO_ROLE=bid_manager
NEXT_PUBLIC_LANGSMITH_URL=
```

The demo identity headers are for local demonstration only; production must
use real authentication and authorization.

## Release checklist

Before calling the implementation complete:

- [ ] FastAPI starts from the project root and `/health` and `/ready` behave
      correctly.
- [ ] Migrations, seed, and KB ingestion are idempotent.
- [ ] PostgreSQL/pgvector deployment has been tested in addition to SQLite.
- [ ] Real provider model IDs, keys, quotas, and cost limits are verified.
- [ ] The company KB is indexed once and not re-embedded per tender.
- [ ] Original files and corrigendum are uploaded in separate UI actions.
- [ ] v1 produces `77.34/BID_WITH_CONDITIONS`.
- [ ] v2 produces `78.80/NO_BID` because the ISO hard gate fails.
- [ ] v1 approval is superseded and v1 drafts are visibly stale after v2.
- [ ] All displayed facts have page-level evidence.
- [ ] Gate 1 and Gate 2 are human-controlled and auditable.
- [ ] Gold labels and safety fixtures are evaluator-isolated.
- [ ] Guardrails, PII handling, budgets, replay, and audit logs are tested.
- [ ] XLSX, DOCX, ICS, and audit JSON exports open successfully.
- [ ] Frontend click-through works without developer-console actions.
- [ ] The demo explicitly says that the tender/company are synthetic and
      focused coverage/metrics are not measured full-pack claims.

## License and provenance

The tender, company, safety fixtures, and expected results in `demo_data/`
are synthetic fixtures created for the AgentOps 2026 demonstration. Do not
represent them as official government documents, real company records, or
measured production performance.
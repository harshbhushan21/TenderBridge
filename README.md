<div align="center">

# TenderBridge

**An agentic bid / no-bid copilot for public IT-infrastructure tenders: it turns a tender pack into a verified compliance matrix, an evidence-backed recommendation and a cited response draft, with a human approving every decision.**

AgentOps 2026 · Track 01 (Multi-agent systems) · CGI domain: IT Infrastructure · Team BR01/MP04 (HX-2SJA)

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-agents-1C3C3C)
![Next.js](https://img.shields.io/badge/Next.js-15-000000?logo=nextdotjs&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-4169E1?logo=postgresql&logoColor=white)

### 🎥 Live Demo Video: [Watch TenderBridge Demo](INSERT_DEMO_VIDEO_URL)

</div>

> **Demo data is synthetic.** `TDR-001` is a simulated State Data Centre O&M tender from a fictional buyer, and Nimbus Digital Services is a fictional bidder. Nothing in this repository is CGI data, and TenderBridge never submits anything to GeM, CPPP or any other portal.

## Contents

1. [Overview](#overview)
2. [Key features](#key-features)
3. [Architecture](#architecture)
4. [Technology stack](#technology-stack)
5. [Repository structure](#repository-structure)
6. [Quick start](#quick-start)
7. [Configuration: API keys and cloud services](#configuration-api-keys-and-cloud-services)
8. [Using TenderBridge](#using-tenderbridge)
9. [Testing and evaluation](#testing-and-evaluation)
10. [Security and responsible AI](#security-and-responsible-ai)
11. [Limitations](#limitations)
12. [Team and acknowledgments](#team-and-acknowledgments)

## Overview

### The problem

A public tender for IT infrastructure is a pack of PDFs, annexures and spreadsheets that runs to dozens of pages. Before deciding whether to bid, a bid team must find every mandatory requirement, prove each one against company records (turnover, certificates, past projects, staff), weigh the contract risks, and then redo much of that work when the buyer issues a corrigendum. It is slow and repetitive, and one missed expiry date can disqualify the bid.

### The solution

TenderBridge is a multi-step agent workflow built on LangGraph. It:

1. **Reads the tender** and extracts every requirement with its document, page and text span.
2. **Checks eligibility** against a persistent company knowledge base, choosing the right method for each item: **deterministic rules** for numbers, dates and certificates, and **hybrid retrieval (RAG)** to find supporting evidence.
3. **Scores the bid** with a weighted policy in which any failed hard gate overrides the score.
4. **Stops for a human** (Gate 1) before anything is decided, and again (Gate 2) before a drafted response section is accepted.
5. **Handles corrigenda** on the same tender: it diffs the change into typed edits, re-runs only the affected checks, creates a new version and shows how the recommendation moved.

### How it differs from a PDF chatbot

| A PDF chatbot | TenderBridge |
|---|---|
| Answers the questions you think to ask | Extracts **every** requirement and checks each one |
| An LLM guesses at dates and amounts | Dates, amounts, thresholds and hard gates are decided **in code**, never by a model |
| Answers may not say where they came from | Every requirement, verdict and draft claim carries **document, page and text span** |
| One chat thread | A versioned **tender workspace**: amendments, re-analysis, version comparison |
| No accountability | **Role-based approvals**, version-bound decisions and a full **audit trail** |
| No visibility into the agent | **AgentOps** dashboard (time, calls, tokens, cost) and optional **LangSmith** traces |

## Key features

**Analysis and decisions**
- Requirement extraction in batches of sections, combining model output with a rules-based extractor so nothing a model skips is lost.
- **13 hard gates** (pre-qualification) evaluated by deterministic rule tools: turnover with the MSE relaxation, OR-branch similar-work rules, certificate validity on the deadline, personnel, registrations and declarations.
- Commercial risk register: 9 contract clauses compared with the company's approved risk positions (`within_policy`, `review`, `escalate`).
- Weighted bid score (strategic fit, technical capability, delivery capacity, eligibility confidence, commercial risk), giving `BID`, `BID_WITH_CONDITIONS` or `NO_BID`.

**Human in the loop**
- **Gate 1** (bid decision) and **Gate 2** (draft review) are LangGraph `interrupt()` points backed by durable checkpoints, so a paused run survives an API restart.
- Only a Bid Manager or Admin can decide; refusals are audited. Decisions are **bound to a tender version**.

**Corrigendum handling**
- Upload a corrigendum to the same tender. It is parsed into typed changes (Part A amendments and Part B pre-bid clarifications) with before/after values and the checks each one invalidates. You preview the changes, then confirm to create a new version.
- **Impact re-analysis** re-runs only the affected checks and reuses unchanged results; earlier approvals become `superseded` and older drafts `stale`.
- Version comparison: score, recommendation, changed verdicts and changed contract terms.

**Cited drafting**
- One response section is drafted from company documents approved for reuse. Every sentence cites numbered evidence, a verifier checks each claim against its own citations, unsupported claims are rewritten or removed, and the section waits at Gate 2. Approved sections export to DOCX.

**Trust and observability**
- Prompt-injection screening of visible text, hidden text and PDF metadata; suspicious spans are quarantined and logged as guardrail events.
- Role- and sensitivity-filtered retrieval, applied **before** ranking.
- AgentOps page: runs, analysis time, LLM calls, tokens, cost per model, per-node latency, evaluation scores and guardrail events. Optional LangSmith tracing with redaction.
- Exports: compliance and eligibility XLSX, draft and no-bid DOCX, deadline calendar (ICS) and audit JSON.

## Architecture

```mermaid
flowchart LR
    UI["Next.js web UI<br/>dashboard · tender workspace<br/>knowledge base · AgentOps"]
    API["FastAPI<br/>REST + SSE"]
    subgraph Agents["LangGraph"]
        AG["Analysis graph<br/>to Gate 1"]
        DG["Drafting graph<br/>to Gate 2"]
    end
    TOOLS["Deterministic tools<br/>rules · scoring · amendment diff"]
    RAG["Hybrid retrieval<br/>BM25 + vectors, RRF"]
    LLM["LLM providers<br/>Anthropic · Gemini · Groq"]
    DB[("PostgreSQL + pgvector<br/>or SQLite")]
    CK[("Checkpoints")]
    EMB["BGE-M3 embeddings<br/>(local)"]
    LS["LangSmith<br/>(optional)"]

    UI <--> API
    API --> Agents
    Agents --> TOOLS
    Agents --> RAG
    Agents --> LLM
    RAG --> EMB
    RAG --> DB
    TOOLS --> DB
    Agents --> CK
    Agents -. traces .-> LS
```

### The agent graphs

The **analysis graph** runs in a background thread and streams node events to the UI over SSE:

```text
intake_guard → load_tender → shred_requirements → merge_and_dedupe → extract_key_facts
  → reconcile_corrigenda → route_requirements → eligibility_and_risk → bid_score
  → gate1_review (interrupt: human decision)
       ├─ no bid → write_no_bid_report → finalize
       └─ bid    → finalize
```

The **drafting graph** starts after a Gate 1 bid approval and works on the saved analysis, without re-running it:

```text
plan_response → write_sections → verify_claims ⇄ rewrite_failed (bounded)
  → gate2_review (interrupt: approve / edit / request changes / reject) → finalize
```

### Rules decide, retrieval finds evidence

| Question | Method |
|---|---|
| Is turnover ≥ ₹45 Cr over three years? Is ISO 27001 valid on the bid deadline? Does a project meet the similar-work OR rule? | **Deterministic rule tools** over structured company facts (SQL). Authoritative. |
| Which company document supports this requirement? Which approved passage can a draft cite? | **Hybrid retrieval**: BM25 + vector search fused with reciprocal rank fusion, filtered by role, sensitivity and reuse approval before ranking. |
| What does this tender require? What changed in the corrigendum? | **LLM extraction** with a rules-based fallback; corrigendum dates and amounts are diffed in code. |

Tender text and company text live in **separate retrieval scopes** and are never mixed. A failed mandatory gate overrides any weighted score.

### State, checkpoints and tracing

- LangGraph checkpoints are stored in PostgreSQL (`CHECKPOINT_URL`) or a local SQLite file, so a run paused at a gate resumes after a restart. A run that a restart interrupted is recovered on startup.
- Results, versions, reviews and the audit log are stored through SQLAlchemy (Alembic migrations).
- Every node emits events and audit entries. With LangSmith enabled, traces follow `analysis_run → graph → node → tool / retriever / LLM`, and the Gate 1 resume continues in the same trace thread.

## Technology stack

| Layer | Technology | Role |
|---|---|---|
| Agent orchestration | **LangGraph** | Analysis and drafting graphs, `interrupt()` gates, Postgres/SQLite checkpointers |
| LLM access | **LangChain** chat models | Structured output for extraction and drafting; per-node routing, rate limits, response cache, cost budget |
| LLM providers | **Anthropic** (Claude Haiku 5.5, Sonnet 5.5), **Google Gemini**, **Groq** | Requirement extraction, key-fact gap filling, drafting; the app also runs fully offline with deterministic fallbacks |
| Embeddings | **BAAI/bge-m3** via sentence-transformers | Local 1024-d embeddings; an offline `hash` embedder is the zero-download default |
| Backend | **FastAPI**, Pydantic, SQLAlchemy, Alembic | REST API, SSE run events, background runs |
| Database | **PostgreSQL 16 + pgvector** (Docker or Supabase), or **SQLite** | Facts, tenders, versions, chunks and vectors, results, audit log |
| Documents | PyMuPDF, pypdf, python-docx, openpyxl, Tesseract OCR | Parsing PDFs (including scanned pages), DOCX and XLSX |
| Guardrails | Custom checks + Microsoft Presidio (optional) | Injection screening, PII masking, claim and citation verification |
| Observability | **LangSmith**, built-in AgentOps page | Traces, per-run cost and latency |
| Frontend | **Next.js 15**, React 19, Tailwind CSS 4 | Dashboard, tender workspace, knowledge base, AgentOps |
| Tooling | **uv**, pytest, ruff, mypy | Reproducible environment and checks |

## Repository structure

```text
TenderBridge/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app factory; recovers runs interrupted by a restart
│   │   ├── api/               # routers: tenders, amendments, drafts, kb, exports, ops, health
│   │   ├── agents/            # LangGraph graphs, nodes, Gate 1/2, runner, checkpoints, hard gates
│   │   ├── tools/             # deterministic rules, bid scoring, amendment diff, tender/KB search
│   │   ├── retrieval/         # chunker, embeddings, BM25, pgvector/in-Python vectors, hybrid RRF
│   │   ├── ingestion/         # parsers, OCR, sectionizer, upload pipeline, KB ingest, corrigendum parser
│   │   ├── knowledge/         # structured-fact seeding, expiring-credential checks
│   │   ├── llm/               # model factory, routing, rate limits, cache, budget, prompts
│   │   ├── guardrails/        # file security, injection, PII, claim/citation verifiers, policy
│   │   ├── services/          # Gate 1, amendments, versions, comparison
│   │   ├── exports/           # XLSX, DOCX, ICS, audit JSON
│   │   ├── evals/             # evaluation harness (dev.py evals)
│   │   ├── ops/               # events (SSE), audit, metrics, LangSmith tracing + redaction
│   │   ├── db/ · schemas/     # ORM models, repositories, Alembic migrations · Pydantic contracts
│   │   └── core/              # settings, roles, errors, logging
│   ├── scripts/               # init_db, seed facts, ingest KB, demo cases, re-embed, llm-check
│   └── tests/                 # unit and integration tests
├── frontend/                  # Next.js app (src/app pages, src/components, typed API client in src/lib)
├── demo_data/                 # synthetic tender, company KB, structured facts, config and gold files
├── docs/                      # API contract, module interfaces, design decisions
├── dev.py                     # cross-platform task runner (Makefile wraps it)
├── docker-compose.yml         # local PostgreSQL 16 + pgvector
├── pyproject.toml · uv.lock   # Python dependencies (managed by uv)
└── .env.example               # configuration template
```

Runtime files (uploads, parsed text, exports, the LLM cache, evaluation reports) are written to `storage/`, which is git-ignored.

## Quick start

TenderBridge runs on **macOS, Linux and Windows**. Every command goes through `dev.py` and needs only `uv`; on macOS/Linux, `make <command>` is a shortcut for the same thing.

### 1. Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | latest | Everything. uv installs Python 3.13 itself (pinned in `.python-version`). |
| [Git](https://git-scm.com/) | any | Cloning |
| [Node.js](https://nodejs.org/) | 20 or newer (`frontend/.nvmrc` pins 22) | The web UI |
| [Tesseract OCR](https://tesseract-ocr.github.io/) | any | Optional: reading scanned pages (without it they index as empty) |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | any | Optional: a local PostgreSQL + pgvector |

Install uv:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Tesseract: `brew install tesseract` (macOS), `sudo apt install tesseract-ocr` (Ubuntu), or the [UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki) on Windows (add it to `PATH`).

### 2. Clone the repository

```bash
git clone https://github.com/harshbhushan21/TenderBridge.git
cd TenderBridge
```

### 3. Install dependencies and create `.env`

```bash
uv run python dev.py setup
```

This runs `uv sync`, which **creates and manages the virtual environment in `.venv/` for you**, installs the exact locked versions from `uv.lock`, and copies `.env.example` to `.env`. You do not need to create a `venv` or run `pip` yourself; prefix commands with `uv run` and they use `.venv` automatically. If you want the environment active in your shell anyway:

```bash
source .venv/bin/activate        # macOS / Linux
.venv\Scripts\activate           # Windows
```

The default `.env` works with **no API keys**: SQLite, the offline `hash` embedder and deterministic stand-ins for the LLMs (`fake:*`).

### 4. Check the machine

```bash
uv run python dev.py doctor
```

`doctor` checks Python, dependencies, Node.js, Tesseract, the integrity of the demo data (SHA-256), `.env` and the database connection.

### 5. Create the database and load the company knowledge base

```bash
uv run python dev.py ingest-kb
```

This creates the tables, seeds the structured company facts and indexes the 52 knowledge-base documents. It is idempotent: a second run skips unchanged files. (For PostgreSQL, see [Cloud PostgreSQL + pgvector](#cloud-postgresql--pgvector).)

### 6. Start the application

```bash
uv run python dev.py demo
```

This starts the API and the web UI together (Ctrl+C stops both). The first run installs the frontend packages. To run them separately in two terminals:

```bash
uv run python dev.py api      # FastAPI on http://localhost:8000
uv run python dev.py web      # Next.js on http://localhost:3000
```

### 7. Open the app

| URL | What |
|---|---|
| <http://localhost:3000> | Web UI |
| <http://localhost:8000/docs> | Interactive API documentation |
| <http://localhost:8000/health> | Health check |

### 8. Verify the installation

```bash
uv run python dev.py test        # backend tests on a throwaway SQLite database
uv run python dev.py web-check   # frontend typecheck + production build
```

`uv run python dev.py help` lists every command.

## Configuration: API keys and cloud services

All settings live in `.env` (git-ignored). Environment variables override `.env`. **Never commit `.env` or real keys.**

### LLM providers

Without keys, TenderBridge runs offline: `LLM_FAST=fake:fast` and `LLM_STRONG=fake:strong` use deterministic extractors and an extractive drafter. To use real models, set the two tiers to a real `provider:model` and add the key for each provider you use.

Model calls are made only for **requirement extraction**, **key-fact gap filling**, **drafting** and the **draft rewrite**. Arithmetic, dates, hard gates, scoring, citation checks and exports are always done in code.

Per-node routing lives in [`demo_data/demo_config/llm_routing_and_budget.json`](demo_data/demo_config/llm_routing_and_budget.json). For each node, TenderBridge uses the planned primary model if its provider has a key, then the planned fallback, then the `LLM_FAST` / `LLM_STRONG` tier model.

| Node | Primary | Fallback |
|---|---|---|
| Requirement extraction, key-fact gaps | `anthropic:claude-haiku-5-5` | `google_genai:gemini-3.1-flash-lite` |
| Section drafting and rewrite | `anthropic:claude-sonnet-5-5` | `groq:openai/gpt-oss-120b` |

**Option A: Anthropic (Claude).** This is the configuration used for the demo video.

1. Create a key at [console.anthropic.com](https://console.anthropic.com/) → API keys.
2. In `.env`:
   ```bash
   LLM_FAST=anthropic:claude-haiku-5-5
   LLM_STRONG=anthropic:claude-sonnet-5-5
   ANTHROPIC_API_KEY=<your-anthropic-key>
   MAX_COST_USD=0.50               # optional per-run cost cap
   ```

**Option B: Google Gemini and Groq (free tiers).**

1. Gemini key: [aistudio.google.com/apikey](https://aistudio.google.com/apikey). Groq key: [console.groq.com/keys](https://console.groq.com/keys).
2. In `.env`:
   ```bash
   LLM_FAST=google_genai:gemini-3.1-flash-lite
   LLM_STRONG=groq:openai/gpt-oss-120b
   GOOGLE_API_KEY=<your-gemini-key>     # GEMINI_API_KEY also works
   GROQ_API_KEY=<your-groq-key>
   ```

**Verify connectivity** before a demo:

```bash
uv run python dev.py llm-check          # routing, keys, limits and expected calls/tokens/cost per tender; sends nothing
uv run python dev.py llm-check --ping   # one tiny request per configured model
```

Free-tier safety is built in. Calls wait for room in each model's per-minute window, a `429` is retried after the provider's suggested delay, and identical inputs are answered from a local cache (`LLM_CACHE=true`; cached calls cost nothing and are labelled in AgentOps). `MAX_COST_USD` and `MAX_LLM_CALLS` cap each run.

### Hugging Face embeddings (BGE-M3)

The default `EMBEDDING_PROVIDER=hash` needs no download. For semantic retrieval, BAAI/bge-m3 runs **locally** through sentence-transformers:

- **No API key or Hugging Face token is required.** `HF_TOKEN` is optional and only speeds up downloads.
- The first use downloads the model (about 2.3 GB). Apple GPU or CUDA is used when available.
- Embeddings are 1024-dimensional and are generated when documents are indexed and for each query.

```bash
# .env
EMBEDDING_PROVIDER=huggingface:BAAI/bge-m3
EMBEDDING_DIM=1024
```

After switching embedders, regenerate the stored vectors (search ignores vectors from a different embedder until you do):

```bash
uv run python dev.py reembed --dry-run   # count vectors made by another embedder
uv run python dev.py reembed             # regenerate them in place
```

### Cloud PostgreSQL + pgvector

SQLite needs no setup. For PostgreSQL with pgvector (vector search runs in SQL):

**Local, with Docker**

```bash
uv run python dev.py db-up       # PostgreSQL 16 + pgvector 0.8 on localhost:5433
```

```bash
# .env
DATABASE_URL=postgresql+psycopg://tenderbridge:tenderbridge@localhost:5433/tenderbridge
CHECKPOINT_URL=postgresql://tenderbridge:tenderbridge@localhost:5433/tenderbridge
```

**Cloud, with Supabase** (the free plan is enough; the project uses about 20 MB):

1. Create a project at [supabase.com](https://supabase.com/).
2. In the SQL editor, enable pgvector:
   ```sql
   create extension if not exists vector with schema public;
   ```
3. Under **Connect**, copy the **Session pooler** URI (IPv4). The transaction pooler breaks prepared statements, so don't use it.
4. In `.env` (note the two different driver prefixes):
   ```bash
   DATABASE_URL=postgresql+psycopg://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
   CHECKPOINT_URL=postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
   ```

**Then, for either option**, apply the migrations and load the knowledge base:

```bash
uv run python dev.py migrate     # Alembic: tables, pgvector extension, full-text indexes
uv run python dev.py ingest-kb   # seed facts and index the 52 KB documents
```

Everyone who shares a database must use the same `EMBEDDING_PROVIDER`. `dev.py reset-db` drops all tables, so never run it against a shared database.

### LangSmith tracing

1. Create a key at [smith.langchain.com](https://smith.langchain.com/) → **Settings → API Keys**.
2. In `.env`:
   ```bash
   LANGSMITH_TRACING=true
   LANGSMITH_API_KEY=<your-langsmith-key>
   LANGSMITH_PROJECT=tenderbridge
   # LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com   # only for EU-region accounts
   ```
3. Restart the API and run an analysis. Traces appear in the `tenderbridge` project as `analysis_run → graph → node → tool / retriever / LLM`. Ingestion, amendments, Gate decisions, scoring, guardrail events and evaluations are traced too. The AgentOps page shows whether tracing is on and links to LangSmith.

Nothing is sent unless tracing is enabled **and** a key is set. Trace inputs and outputs are redacted (emails, phone numbers, PAN/Aadhaar, API keys), and restricted KB text is withheld.

### Sanitized `.env` reference

```bash
# Paths
DEMO_DATA_DIR=demo_data
STORAGE_DIR=storage

# Database (SQLite default; see above for PostgreSQL / Supabase)
DATABASE_URL=sqlite:///storage/tenderbridge.db
CHECKPOINT_URL=

# LLMs (fake:* = offline)
LLM_FAST=fake:fast
LLM_STRONG=fake:strong
LLM_TIMEOUT_S=60
ANTHROPIC_API_KEY=
GOOGLE_API_KEY=
GROQ_API_KEY=
LLM_CACHE=true
SHRED_WITH_LLM=true
SHRED_BATCH_TOKENS=8000

# Embeddings
EMBEDDING_PROVIDER=hash                 # or huggingface:BAAI/bge-m3
EMBEDDING_DIM=1024
RERANKER=none

# Tracing
LANGSMITH_TRACING=false
LANGSMITH_PROJECT=tenderbridge
LANGSMITH_API_KEY=

# Budgets and limits
MAX_COST_USD=5
MAX_LLM_CALLS=400
MAX_RETRIES=1
MAX_REWRITES=2
MAX_PARALLEL_LLM=4

# Application
DEMO_MODE=true
ANALYSIS_MODE=focused
DEFAULT_COMPANY_ID=NIMBUS-001
CORS_ORIGINS=http://localhost:3000
MAX_UPLOAD_MB=50
```

[`.env.example`](.env.example) has every variable with comments.

## Using TenderBridge

The walkthrough below uses the bundled demo tender in `demo_data/tender/TDR-001/original/`. Pick the role in the account menu at the top right: **Bid Manager** or **Analyst**.

1. **Review the company knowledge base.** The dashboard and the **Knowledge base** page show 52 indexed documents, structured facts (financials, certificates, projects, people, risk positions) and credential warnings, for example ISO 27001 expiring on 10 Nov 2026.
2. **Create a tender.** Under **New tender**, enter a title, buyer and reference number, then upload `notice.pdf`, `main_rfp.pdf`, `annexures.pdf` and `price_schedule_boq.xlsx`. Keep the corrigendum for later. Each file is validated, screened for injections, parsed and indexed.
3. **Analyze.** When every file is indexed, click **Analyze**. The progress strip follows each graph node live.
4. **Review the recommendation (Gate 1).** The Overview shows the recommendation, the weighted score, the 13 hard gates and the factor breakdown. For the demo tender: **BID WITH CONDITIONS, 77.34**.
5. **Inspect the evidence.** On **Requirements**, click any row to see the tender clause and page, the rule trace and the company evidence. Example: REQ-PQ-06, where ISO 27001 is valid until 10 Nov against a 6 Nov deadline. **Risks** shows the contract-clause register.
6. **Decide.** As an Analyst, **Approve bid** is refused and the refusal is audited. As a Bid Manager, add a reason and click **Approve bid**, **No bid** or **Defer**.
7. **Draft the response.** After a bid approval, **Response draft → Draft the response** writes a cited section. Click an `[n]` marker to see its source, then approve, edit, request changes or reject it at Gate 2. Download the approved section as DOCX.
8. **Apply a corrigendum.** On **Documents & corrigenda**, upload `corrigendum.pdf`, review the typed changes, click **Confirm v2**, then **Re-analyse impact**. For the demo tender, the deadline moves to 20 Nov, after ISO 27001 expires, so the result becomes **NO BID, 78.80**: the score rises but a hard gate fails.
9. **Compare versions.** **Versions** shows v1 against v2: REQ-PQ-06 changes from Meets to Gap, and the payment, PBG and SLA-cap terms change.
10. **Audit and operations.** **Activity** lists every upload, decision, refusal and confirmation by user and version. **AgentOps** shows runs, analysis time, LLM calls, tokens, cost per model, per-node latency, evaluation scores and guardrail events.

### Roles

| Role | Can read | Can do |
|---|---|---|
| `analyst` | KB documents tagged for analysts | Upload, analyze, view. **Cannot** decide Gate 1 or approve Gate 2. |
| `writer` | Analyst and writer documents | Edit drafts, request changes |
| `bid_manager` | All KB documents, including risk positions | Everything above, plus Gate 1, Gate 2 and confirming amendments |
| `admin` | Everything | KB ingestion and settings |

Identity comes from demo headers (`X-User`, `X-Role`) set by the role switcher. A production deployment would use real authentication.

### Command-line demo cases

```bash
uv run python dev.py demo-cli CASE-1   # v1 analysis to Gate 1: 77.34 BID_WITH_CONDITIONS
uv run python dev.py demo-cli CASE-2   # v1, then Corrigendum No. 1 and impact re-analysis: 78.80 NO_BID
```

## Testing and evaluation

```bash
uv run python dev.py test        # 148 backend tests on a throwaway SQLite database
uv run python dev.py test-pg     # the same tests on PostgreSQL + pgvector (starts Docker)
uv run python dev.py lint        # ruff
uv run python dev.py typecheck   # mypy
uv run python dev.py evals       # full pipeline on TDR-001 in a fresh database, scored against the gold files
uv run python dev.py web-check   # frontend typecheck + production build
```

`dev.py evals` writes `storage/evals/report.json`, and the AgentOps page shows its scores.

### Measured results

From `dev.py evals` on 24 Oct 2026, with BGE-M3 embeddings and the deterministic (no-LLM) extractors:

| Metric | Result |
|---|---|
| Mandatory-requirement recall | **100%** (v1 85/85, v2 89/89 gold items) |
| All-requirement recall | 98.9% |
| Mandatory-flag accuracy | 95.7% (v1), 95.9% (v2) |
| Precision | 25–27%: the extractor favours recall, and the gold set is not exhaustive |
| Assessments | v1 77.34 `BID_WITH_CONDITIONS` and v2 78.80 `NO_BID` reproduced exactly |
| Retrieval recall@6 (40 gold questions) | 0.925 (tender 1.00, company 0.85); MRR 0.67 |
| Injection traps caught | 4/4 |
| Claim verifier | 6/6 bad claims struck; 6 of 9 good claims also struck (deterministic checks only) |
| End-to-end time (no LLM calls) | ~78 s: v1 upload and indexing 47 s, v1 analysis 12 s, corrigendum 2 s, v2 impact analysis 13 s |

**One observed real-model run** (the demo recording, Claude Haiku 5.5 + Sonnet 5.5, empty cache): v1 analysis, one drafted section and the v2 impact re-analysis took 9 LLM calls (3 served from cache), about 117k tokens and **$0.049** in total, as reported by the AgentOps page. The v1 analysis took about 3 minutes. This is a single run, not a benchmark.

## Security and responsible AI

- **Untrusted documents:** every uploaded file and sentence is treated as data. Visible instructions, hidden text and PDF-metadata injections are quarantined, kept out of the index and recorded as guardrail events.
- **Upload validation:** extension, MIME type, size, archive limits, path traversal and duplicate hashes.
- **PII masking:** personal names (from HR facts) and identifiers such as emails, phone numbers and PAN/Aadhaar are masked when the knowledge base is indexed, so prompts only see masked text. Presidio is used when available, with regex masks otherwise. LangSmith traces are redacted separately.
- **Role-based access:** `allowed_roles`, sensitivity and reuse approval are enforced inside retrieval, before ranking. Risk positions are visible to Bid Managers only, and refusals are audited.
- **Evidence verification:** every verdict and draft claim cites a document, page and span. The claim verifier checks citations, values, negations and expiry, and unsupported claims are removed from drafts.
- **Human control:** no bid decision or draft is final without a Bid Manager at Gate 1 or Gate 2. Decisions are version-bound, and a confirmed amendment supersedes earlier approvals.
- **Bounded agents:** no agent can submit to a portal, send email or write to the knowledge base. Retries, rewrites, concurrency, calls and cost are capped per run.
- **Evaluation hygiene:** gold labels in `demo_data/evaluation/` are evaluator-only and never reach agent context.

## Limitations

- **Synthetic data:** the tender, the company and the expected results are fictional fixtures created for this demonstration.
- **Focused analysis:** the live demo checks a focused subset (`ANALYSIS_MODE=focused`): 42 of 105 gold requirements.
- **Demo estimates:** strategic fit, technical capability and delivery capacity scores are configured demo estimates (`backend/app/agents/analysis_inputs.json`), not computed from documents.
- **Demo identity:** users and roles come from request headers, not a real identity provider.
- **Deterministic verifier and screening:** the claim verifier uses deterministic checks only and also strikes some correct claims. Injection screening is heuristic; a model-based screen is planned but not wired.
- **Local files:** uploaded files stay on the machine that received them, so a shared database cannot open another machine's uploads.

## Team and acknowledgments

Built for **AgentOps 2026: The Agentic Edition** (SDG Club MIT Bengaluru × CGI), Track 01, Multi-agent systems.

| Member | Focus |
|---|---|
| **Harsh Bhushan** (team leader), MIT Bengaluru | Agent graph (LangGraph), deterministic rules and scoring, guardrails, LangSmith tracing and evaluations |
| **Swarnim Rai**, MIT Bengaluru | Ingestion and RAG pipeline, facts store, FastAPI backend, web UI |

Built with [LangGraph](https://github.com/langchain-ai/langgraph), [LangChain](https://github.com/langchain-ai/langchain), [LangSmith](https://smith.langchain.com/), [FastAPI](https://fastapi.tiangolo.com/), [Next.js](https://nextjs.org/), [PostgreSQL](https://www.postgresql.org/) + [pgvector](https://github.com/pgvector/pgvector), [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3), [PyMuPDF](https://pymupdf.readthedocs.io/), [Tesseract](https://github.com/tesseract-ocr/tesseract), [Microsoft Presidio](https://microsoft.github.io/presidio/) and [uv](https://docs.astral.sh/uv/). Models from Anthropic, Google and Groq.

More detail: [API contract](docs/api_contract.md) · [Module interfaces](docs/interfaces.md) · [Design decisions](docs/decisions.md) · [Demo data pack](demo_data/README.md)

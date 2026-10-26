# TenderBridge

An agentic bid / no-bid copilot for public IT-infrastructure tenders. It turns a tender pack into a
verified compliance matrix, an evidence-backed recommendation and a cited response draft, with a human
approving every decision.

![TenderBridge demo preview](docs/media/demo-preview.gif)

**Demo video (2:57):** [Download the MP4](docs/media/tenderbridge-demo.mp4)

## About the project

A public tender for IT infrastructure is a pack of PDFs, annexures and spreadsheets that runs to dozens
of pages. Before deciding whether to bid, a bid team must find every mandatory requirement, prove each
one against company records (turnover, certificates, past projects, staff), weigh the contract risks,
and then redo much of that work when the buyer issues a corrigendum. It is slow and repetitive, and one
missed expiry date can disqualify the bid.

TenderBridge is a multi-step agent workflow built on LangGraph:

- **Reads the tender** and extracts every requirement with its document, page and text span.
- **Checks eligibility** against a persistent company knowledge base, choosing the right method for
  each item: deterministic rules for numbers, dates and certificates, and hybrid retrieval (RAG) to
  find supporting evidence.
- **Scores the bid** with a weighted policy in which any failed hard gate overrides the score.
- **Stops for a human** at Gate 1 before anything is decided, and again at Gate 2 before a drafted
  response section is accepted.
- **Handles corrigenda** on the same tender: it diffs the change into typed edits, re-runs only the
  affected checks, creates a new version and shows how the recommendation moved.

Unlike a PDF chatbot, it extracts and checks every requirement instead of answering the questions you
think to ask. Dates, amounts, thresholds and hard gates are decided in code, never by a model, and every
requirement, verdict and draft claim carries its document, page and text span. Work happens in a
versioned tender workspace with role-based approvals, version-bound decisions, a full audit trail, and
an AgentOps dashboard with optional LangSmith traces.

## Features

**Analysis and decisions**
- Requirement extraction in batches of sections, combining model output with a rules-based extractor
  so nothing a model skips is lost
- 13 hard gates (pre-qualification) evaluated by deterministic rule tools: turnover with the MSE
  relaxation, OR-branch similar-work rules, certificate validity on the deadline, personnel,
  registrations and declarations
- A commercial risk register: 9 contract clauses compared with the company's approved risk positions
  (`within_policy`, `review`, `escalate`)
- A weighted bid score (strategic fit, technical capability, delivery capacity, eligibility confidence,
  commercial risk), giving `BID`, `BID_WITH_CONDITIONS` or `NO_BID`

**Human in the loop**
- Gate 1 (bid decision) and Gate 2 (draft review) are LangGraph `interrupt()` points backed by durable
  checkpoints, so a paused run survives an API restart
- Only a Bid Manager or Admin can decide, and refusals are audited
- Decisions are bound to a tender version

**Corrigendum handling**
- A corrigendum uploaded to the same tender is parsed into typed changes (Part A amendments and Part B
  pre-bid clarifications) with before/after values and the checks each one invalidates; you preview,
  then confirm to create a new version
- Impact re-analysis re-runs only the affected checks and reuses unchanged results; earlier approvals
  become `superseded` and older drafts `stale`
- Version comparison: score, recommendation, changed verdicts and changed contract terms

**Cited drafting**
- One response section drafted from company documents approved for reuse. Every sentence cites numbered
  evidence, a verifier checks each claim against its own citations, unsupported claims are rewritten or
  removed, and the section waits at Gate 2. Approved sections export to DOCX.

**Trust and observability**
- Prompt-injection screening of visible text, hidden text and PDF metadata; suspicious spans are
  quarantined and logged as guardrail events
- Role- and sensitivity-filtered retrieval, applied before ranking
- An AgentOps page with runs, analysis time, LLM calls, tokens, cost per model, per-node latency,
  evaluation scores and guardrail events, plus optional LangSmith tracing with redaction
- Exports: compliance and eligibility XLSX, draft and no-bid DOCX, a deadline calendar (ICS) and audit JSON

| Gate 1 | Evidence | Version comparison |
| --- | --- | --- |
| ![Gate 1](docs/media/screens/gate1-v1.jpg) | ![Evidence](docs/media/screens/evidence.jpg) | ![Versions](docs/media/screens/versions.jpg) |

| Cited draft | Corrigendum | AgentOps |
| --- | --- | --- |
| ![Cited draft](docs/media/screens/draft.jpg) | ![Corrigendum](docs/media/screens/corrigendum.jpg) | ![AgentOps](docs/media/screens/agentops.jpg) |

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

The **analysis graph** runs in a background thread and streams node events to the UI over SSE:

```text
intake_guard → load_tender → shred_requirements → merge_and_dedupe → extract_key_facts
  → reconcile_corrigenda → route_requirements → eligibility_and_risk → bid_score
  → gate1_review (interrupt: human decision)
       ├─ no bid → write_no_bid_report → finalize
       └─ bid    → finalize
```

The **drafting graph** starts after a Gate 1 bid approval and works on the saved analysis, without
re-running it:

```text
plan_response → write_sections → verify_claims ⇄ rewrite_failed (bounded)
  → gate2_review (interrupt: approve / edit / request changes / reject) → finalize
```

**Rules decide, retrieval finds evidence.**

| Question | Method |
| --- | --- |
| Is turnover ≥ ₹45 Cr over three years? Is ISO 27001 valid on the bid deadline? Does a project meet the similar-work OR rule? | Deterministic rule tools over structured company facts (SQL). Authoritative. |
| Which company document supports this requirement? Which approved passage can a draft cite? | Hybrid retrieval: BM25 + vector search fused with reciprocal rank fusion, filtered by role, sensitivity and reuse approval before ranking |
| What does this tender require? What changed in the corrigendum? | LLM extraction with a rules-based fallback; corrigendum dates and amounts are diffed in code |

Tender text and company text live in separate retrieval scopes and are never mixed. A failed mandatory
gate overrides any weighted score.

LangGraph checkpoints are stored in PostgreSQL (`CHECKPOINT_URL`) or a local SQLite file, so a run
paused at a gate resumes after a restart, and a run that a restart interrupted is recovered on startup.
Results, versions, reviews and the audit log are stored through SQLAlchemy (Alembic migrations). Every
node emits events and audit entries; with LangSmith enabled, traces follow
`analysis_run → graph → node → tool / retriever / LLM`, and the Gate 1 resume continues in the same
trace thread.

## Tech stack

| Layer | Technology |
| --- | --- |
| Agent orchestration | LangGraph: analysis and drafting graphs, `interrupt()` gates, Postgres/SQLite checkpointers |
| LLM access | LangChain chat models with structured output; per-node routing, rate limits, response cache, cost budget |
| LLM providers | Anthropic (Claude Haiku 5.5, Sonnet 5.5), Google Gemini, Groq; the app also runs fully offline with deterministic fallbacks |
| Embeddings | BAAI/bge-m3 via sentence-transformers (local, 1024-d); an offline `hash` embedder is the default |
| Backend | FastAPI, Pydantic, SQLAlchemy, Alembic |
| Database | PostgreSQL 16 + pgvector (Docker or Supabase), or SQLite |
| Documents | PyMuPDF, pypdf, python-docx, openpyxl, Tesseract OCR |
| Guardrails | Custom checks, with Microsoft Presidio when available |
| Observability | LangSmith and the built-in AgentOps page |
| Frontend | Next.js 15, React 19, Tailwind CSS 4 |
| Tooling | uv, pytest, ruff, mypy |

## Getting started

**Requirements:** [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python
3.13 itself), Git and Node.js 20+. Optional: Tesseract OCR for scanned pages, and Docker for a local
PostgreSQL. No API keys are needed: the default `.env` uses SQLite, the offline `hash` embedder and
deterministic stand-ins for the LLMs.

```bash
git clone https://github.com/harshbhushan21/TenderBridge.git
cd TenderBridge

uv run python dev.py setup       # install dependencies into .venv and create .env from .env.example
uv run python dev.py doctor      # check Python, dependencies, Node.js, Tesseract, demo data, .env, database
uv run python dev.py ingest-kb   # create tables, seed company facts, index the 52 KB documents (idempotent)
uv run python dev.py demo        # API + web UI together; open http://localhost:3000 (Ctrl+C stops both)
```

`uv` creates and manages the virtual environment in `.venv/` and installs the exact versions in
`uv.lock`; `uv run` always uses it, so there is no separate `venv` or `pip` step. To activate it
yourself, run `source .venv/bin/activate` (macOS/Linux) or `.venv\Scripts\activate` (Windows).

Install uv with `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or
`powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows). Tesseract:
`brew install tesseract`, `sudo apt install tesseract-ocr`, or the
[UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki) on Windows.

### Commands

Every command runs as `uv run python dev.py <command>`; on macOS/Linux, `make <command>` does the same.

| Command | Purpose |
| --- | --- |
| `setup` / `doctor` | Install dependencies and create `.env` / check the machine |
| `ingest-kb` | Create tables, seed company facts and index the knowledge base (idempotent) |
| `demo` | API and web UI together |
| `api` / `web` | FastAPI on http://localhost:8000 (docs at `/docs`) / Next.js on http://localhost:3000 |
| `migrate` | Apply Alembic migrations to `DATABASE_URL` |
| `db-up` / `db-down` | Start / stop PostgreSQL 16 + pgvector in Docker (localhost:5433) |
| `llm-check` | Model routing, keys, limits and expected load per tender; `--ping` tests each model |
| `reembed` | Re-embed stored vectors after changing `EMBEDDING_PROVIDER` (`--dry-run` counts) |
| `demo-cli CASE-1` / `CASE-2` | Run the demo cases from the command line |
| `test` / `test-pg` | Backend tests on SQLite / on PostgreSQL |
| `lint` / `typecheck` / `web-check` | ruff / mypy / frontend typecheck and production build |
| `evals` | Run the pipeline on TDR-001 in a fresh database and score it against the gold files |
| `reset-db` | Drop and recreate tables (destroys data; never run it on a shared database) |

## Configuration

All settings live in `.env` (git-ignored); environment variables override it.
[`.env.example`](.env.example) documents every variable. Never commit `.env` or real keys.

### LLM providers

Without keys, `LLM_FAST=fake:fast` and `LLM_STRONG=fake:strong` run everything offline. Model calls
are made only for requirement extraction, key-fact gap filling, drafting and the draft rewrite;
arithmetic, dates, hard gates, scoring, citation checks and exports are always done in code.

Routing per node is defined in
[`llm_routing_and_budget.json`](demo_data/demo_config/llm_routing_and_budget.json). For each node,
TenderBridge uses the planned primary model if its provider has a key, then the planned fallback, then
the `LLM_FAST` / `LLM_STRONG` tier model.

| Node | Primary | Fallback |
| --- | --- | --- |
| Requirement extraction, key-fact gaps | `anthropic:claude-haiku-5-5` | `google_genai:gemini-3.1-flash-lite` |
| Section drafting and rewrite | `anthropic:claude-sonnet-5-5` | `groq:openai/gpt-oss-120b` |

Anthropic (used for the demo video), with a key from [console.anthropic.com](https://console.anthropic.com/):

```bash
LLM_FAST=anthropic:claude-haiku-5-5
LLM_STRONG=anthropic:claude-sonnet-5-5
ANTHROPIC_API_KEY=<your-anthropic-key>
MAX_COST_USD=0.50                  # optional per-run cost cap
```

Google Gemini and Groq (free tiers), with keys from [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
and [console.groq.com/keys](https://console.groq.com/keys):

```bash
LLM_FAST=google_genai:gemini-3.1-flash-lite
LLM_STRONG=groq:openai/gpt-oss-120b
GOOGLE_API_KEY=<your-gemini-key>   # GEMINI_API_KEY also works
GROQ_API_KEY=<your-groq-key>
```

Run `uv run python dev.py llm-check` to see the routing, keys and expected calls, tokens and cost per
tender (it sends nothing), and add `--ping` to send one tiny request per model. Calls wait for room in
each model's per-minute window, a `429` is retried after the provider's suggested delay, and identical
inputs are answered from a local cache (`LLM_CACHE=true`; cached calls cost nothing and are labelled in
AgentOps). `MAX_COST_USD` and `MAX_LLM_CALLS` cap each run.

### Embeddings (BGE-M3)

The default `EMBEDDING_PROVIDER=hash` needs no download. For semantic retrieval, set
`EMBEDDING_PROVIDER=huggingface:BAAI/bge-m3` (with `EMBEDDING_DIM=1024`). The model runs locally
through sentence-transformers, needs no API key or Hugging Face token (`HF_TOKEN` only speeds up
downloads), downloads about 2.3 GB on first use, and uses Apple GPU or CUDA when available. After
switching embedders, run `uv run python dev.py reembed`; search ignores vectors from a different
embedder until you do.

### PostgreSQL + pgvector

SQLite needs no setup. For PostgreSQL, either start the local container with
`uv run python dev.py db-up` and set:

```bash
DATABASE_URL=postgresql+psycopg://tenderbridge:tenderbridge@localhost:5433/tenderbridge
CHECKPOINT_URL=postgresql://tenderbridge:tenderbridge@localhost:5433/tenderbridge
```

or use Supabase (the free plan is enough; the project uses about 20 MB). Create a project, run
`create extension if not exists vector with schema public;` in the SQL editor, and copy the
**Session pooler** URI (IPv4; the transaction pooler breaks prepared statements):

```bash
DATABASE_URL=postgresql+psycopg://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
CHECKPOINT_URL=postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

Then run `uv run python dev.py migrate` and `uv run python dev.py ingest-kb`. Everyone sharing a
database must use the same `EMBEDDING_PROVIDER`.

### LangSmith

Create a key at [smith.langchain.com](https://smith.langchain.com/) (Settings → API Keys), then set:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=<your-langsmith-key>
LANGSMITH_PROJECT=tenderbridge
# LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com   # only for EU-region accounts
```

Restart the API and run an analysis. Traces appear in the `tenderbridge` project; ingestion,
amendments, gate decisions, scoring, guardrail events and evaluations are traced too, and the AgentOps
page links to LangSmith. Nothing is sent unless tracing is enabled and a key is set. Trace inputs and
outputs are redacted (emails, phone numbers, PAN/Aadhaar, API keys), and restricted KB text is withheld.

## Using TenderBridge

The walkthrough uses the bundled demo tender in `demo_data/tender/TDR-001/original/`. Pick the role in
the account menu at the top right: **Bid Manager** or **Analyst**.

1. **Review the company knowledge base.** The dashboard and the Knowledge base page show 52 indexed
   documents, structured facts and credential warnings, for example ISO 27001 expiring on 10 Nov 2026.
2. **Create a tender.** Under New tender, enter a title, buyer and reference number, then upload
   `notice.pdf`, `main_rfp.pdf`, `annexures.pdf` and `price_schedule_boq.xlsx` (keep the corrigendum for
   later). Each file is validated, screened for injections, parsed and indexed.
3. **Analyze.** When every file is indexed, click Analyze. The progress strip follows each graph node live.
4. **Review the recommendation (Gate 1).** The Overview shows the recommendation, the weighted score,
   the 13 hard gates and the factor breakdown: **BID WITH CONDITIONS, 77.34** for the demo tender.
5. **Inspect the evidence.** On Requirements, click a row to see the tender clause and page, the rule
   trace and the company evidence, for example REQ-PQ-06: ISO 27001 valid until 10 Nov against a 6 Nov
   deadline. Risks shows the contract-clause register.
6. **Decide.** As an Analyst, Approve bid is refused and the refusal is audited. As a Bid Manager, add a
   reason and click Approve bid, No bid or Defer.
7. **Draft the response.** After a bid approval, Response draft → Draft the response writes a cited
   section. Click an `[n]` marker to see its source, approve it at Gate 2 and download it as DOCX.
8. **Apply a corrigendum.** On Documents & corrigenda, upload `corrigendum.pdf`, review the typed
   changes, click Confirm v2, then Re-analyse impact. The deadline moves to 20 Nov, after ISO 27001
   expires, so the result becomes **NO BID, 78.80**: the score rises, but a hard gate fails.
9. **Compare versions.** Versions shows REQ-PQ-06 changing from Meets to Gap, and the payment, PBG and
   SLA-cap terms changing.
10. **Audit and operations.** Activity lists every upload, decision, refusal and confirmation by user and
    version. AgentOps shows runs, analysis time, LLM calls, tokens, cost per model, per-node latency,
    evaluation scores and guardrail events.

| Role | Can read | Can do |
| --- | --- | --- |
| `analyst` | KB documents tagged for analysts | Upload, analyze, view; cannot decide Gate 1 or approve Gate 2 |
| `writer` | Analyst and writer documents | Edit drafts, request changes |
| `bid_manager` | All KB documents, including risk positions | Everything above, plus Gate 1, Gate 2 and confirming amendments |
| `admin` | Everything | KB ingestion and settings |

Identity comes from demo headers (`X-User`, `X-Role`) set by the role switcher; a production deployment
would use real authentication.

## Project structure

```
TenderBridge/
├── backend/
│   ├── app/
│   │   ├── main.py          FastAPI app factory; recovers runs interrupted by a restart
│   │   ├── api/             routers: tenders, amendments, drafts, kb, exports, ops, health
│   │   ├── agents/          LangGraph graphs, nodes, Gate 1/2, runner, checkpoints, hard gates
│   │   ├── tools/           deterministic rules, bid scoring, amendment diff, tender/KB search
│   │   ├── retrieval/       chunker, embeddings, BM25, pgvector/in-Python vectors, hybrid RRF
│   │   ├── ingestion/       parsers, OCR, sectionizer, upload pipeline, KB ingest, corrigendum parser
│   │   ├── knowledge/       structured-fact seeding, expiring-credential checks
│   │   ├── llm/             model factory, routing, rate limits, cache, budget, prompts
│   │   ├── guardrails/      file security, injection, PII, claim/citation verifiers, policy
│   │   ├── services/        Gate 1, amendments, versions, comparison
│   │   ├── exports/         XLSX, DOCX, ICS, audit JSON
│   │   ├── evals/           evaluation harness (dev.py evals)
│   │   ├── ops/             events (SSE), audit, metrics, LangSmith tracing and redaction
│   │   ├── db/, schemas/    ORM models, repositories, Alembic migrations; Pydantic contracts
│   │   └── core/            settings, roles, errors, logging
│   ├── scripts/             init_db, seed facts, ingest KB, demo cases, re-embed, llm-check
│   └── tests/               unit and integration tests
├── frontend/                Next.js app: pages, components, typed API client
├── demo_data/               synthetic tender, company KB, structured facts, config and gold files
├── docs/                    API contract, module interfaces, design decisions, demo media
├── dev.py                   cross-platform task runner (the Makefile wraps it)
└── docker-compose.yml       local PostgreSQL 16 + pgvector
```

Runtime files (uploads, parsed text, exports, the LLM cache, evaluation reports) are written to
`storage/`, which is git-ignored.

## Testing and evaluation

```bash
uv run python dev.py test       # 148 backend tests on a throwaway SQLite database
uv run python dev.py evals      # full pipeline on TDR-001 in a fresh database, scored against the gold files
```

`dev.py evals` writes `storage/evals/report.json`, and the AgentOps page shows its scores. Measured on
24 Oct 2026 with BGE-M3 embeddings and the deterministic (no-LLM) extractors:

| Metric | Result |
| --- | --- |
| Mandatory-requirement recall | 100% (v1 85/85, v2 89/89 gold items) |
| All-requirement recall | 98.9% |
| Mandatory-flag accuracy | 95.7% (v1), 95.9% (v2) |
| Precision | 25–27%: the extractor favours recall, and the gold set is not exhaustive |
| Assessments | v1 77.34 `BID_WITH_CONDITIONS` and v2 78.80 `NO_BID` reproduced exactly |
| Retrieval recall@6 (40 gold questions) | 0.925 (tender 1.00, company 0.85); MRR 0.67 |
| Injection traps caught | 4/4 |
| Claim verifier | 6/6 bad claims struck; 6 of 9 good claims also struck (deterministic checks only) |
| End-to-end time (no LLM calls) | ~78 s: v1 upload and indexing 47 s, v1 analysis 12 s, corrigendum 2 s, v2 impact analysis 13 s |

One observed real-model run (the demo recording, Claude Haiku 5.5 + Sonnet 5.5, empty cache): the v1
analysis, one drafted section and the v2 impact re-analysis took 9 LLM calls (3 served from cache),
about 117k tokens and $0.049 in total, as reported by the AgentOps page. The v1 analysis took about 3
minutes. This is a single run, not a benchmark.

## Security and responsible AI

- **Untrusted documents.** Every uploaded file and sentence is treated as data. Visible instructions,
  hidden text and PDF-metadata injections are quarantined, kept out of the index and recorded as
  guardrail events.
- **Upload validation.** Extension, MIME type, size, archive limits, path traversal and duplicate hashes.
- **PII masking.** Personal names (from HR facts) and identifiers such as emails, phone numbers and
  PAN/Aadhaar are masked when the knowledge base is indexed, so prompts only see masked text. Presidio
  is used when available, with regex masks otherwise. LangSmith traces are redacted separately.
- **Role-based access.** `allowed_roles`, sensitivity and reuse approval are enforced inside retrieval,
  before ranking. Risk positions are visible to Bid Managers only, and refusals are audited.
- **Evidence verification.** Every verdict and draft claim cites a document, page and span. The claim
  verifier checks citations, values, negations and expiry, and unsupported claims are removed from drafts.
- **Human control.** No bid decision or draft is final without a Bid Manager at Gate 1 or Gate 2.
  Decisions are version-bound, and a confirmed amendment supersedes earlier approvals.
- **Bounded agents.** No agent can submit to a portal, send email or write to the knowledge base.
  Retries, rewrites, concurrency, calls and cost are capped per run.
- **Evaluation hygiene.** Gold labels in `demo_data/evaluation/` are evaluator-only and never reach
  agent context.

## Limitations

- The tender, the company and the expected results are synthetic fixtures created for this demonstration.
- The live demo checks a focused subset (`ANALYSIS_MODE=focused`): 42 of 105 gold requirements.
- Strategic fit, technical capability and delivery capacity are configured demo estimates
  (`backend/app/agents/analysis_inputs.json`), not computed from documents.
- Users and roles come from request headers, not a real identity provider.
- The claim verifier uses deterministic checks only and also strikes some correct claims. Injection
  screening is heuristic; a model-based screen is planned but not wired.
- Uploaded files stay on the machine that received them, so a shared database cannot open another
  machine's uploads.

## Team

Built for AgentOps 2026: The Agentic Edition (SDG Club MIT Bengaluru × CGI), Track 01, Multi-agent systems, CGI domain: IT Infrastructure. Team BR01/MP04 (HX-2SJA).

| Member | Focus |
| --- | --- |
| Harsh Bhushan (team leader), MIT Bengaluru | Agent graph (LangGraph), deterministic rules and scoring, guardrails, LangSmith tracing and evaluations |
| Swarnim Rai, MIT Bengaluru | Ingestion and RAG pipeline, facts store, FastAPI backend, web UI |

Further reading: [API contract](docs/api_contract.md) · [Module interfaces](docs/interfaces.md) ·
[Design decisions](docs/decisions.md) · [Demo data pack](demo_data/README.md)

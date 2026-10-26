<div align="center">

<img src="docs/media/banner.svg" alt="TenderBridge: an agentic bid / no-bid copilot for public IT-infrastructure tenders" width="100%">

<br>

![Python](https://img.shields.io/badge/Python-3.13-565449?style=flat-square&logo=python&logoColor=white&labelColor=11120D)
![LangGraph](https://img.shields.io/badge/LangGraph-agents-565449?style=flat-square&logo=langchain&logoColor=white&labelColor=11120D)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-565449?style=flat-square&logo=fastapi&logoColor=white&labelColor=11120D)
![Next.js](https://img.shields.io/badge/Next.js-15-565449?style=flat-square&logo=nextdotjs&logoColor=white&labelColor=11120D)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-565449?style=flat-square&logo=postgresql&logoColor=white&labelColor=11120D)
![Tests](https://img.shields.io/badge/tests-148-16A34A?style=flat-square&labelColor=11120D)

**[Demo](#-demo)** · **[Features](#-key-features)** · **[Architecture](#-architecture)** · **[Quick start](#-quick-start)** · **[Configuration](#-configuration)** · **[Results](#-testing-and-evaluation)**

</div>

<br>

## 🎥 Demo

<div align="center">

<a href="https://cdn.jsdelivr.net/gh/harshbhushan21/TenderBridge@main/docs/media/tenderbridge-demo.mp4">
  <img src="docs/media/demo-preview.gif" alt="TenderBridge demo preview: upload, analysis, Gate 1, evidence, drafting, corrigendum, NO BID, AgentOps" width="88%">
</a>

<sub>Animated preview of the full walkthrough. Click it to play the video.</sub>

<br><br>

[![Watch the full demo](https://img.shields.io/badge/%E2%96%B6%20Watch%20the%20full%20demo-2%3A57-11120D?style=for-the-badge&labelColor=565449)](https://cdn.jsdelivr.net/gh/harshbhushan21/TenderBridge@main/docs/media/tenderbridge-demo.mp4)
&nbsp;
[![Download MP4](https://img.shields.io/badge/%E2%AC%87%20Download-MP4%20%C2%B7%207.7%20MB-11120D?style=for-the-badge&labelColor=565449)](docs/media/tenderbridge-demo.mp4)

</div>

The video is one continuous take of the real app with real Claude calls and no cuts. Long waits are fast-forwarded, and the subtitles say so.

> [!NOTE]
> **Demo data is synthetic.** `TDR-001` is a simulated State Data Centre O&M tender from a fictional buyer, and Nimbus Digital Services is a fictional bidder. Nothing in this repository is CGI data, and TenderBridge never submits anything to GeM, CPPP or any other portal.

## 💡 Why TenderBridge

A public IT-infrastructure tender is a stack of PDFs, annexures and spreadsheets. Before deciding whether to bid, a team must find every mandatory requirement, prove each one against company records (turnover, certificates, past projects, staff), weigh the contract risks, and then redo much of it when the buyer issues a corrigendum. One missed expiry date can disqualify the bid.

TenderBridge is a **LangGraph multi-step agent** that:

1. **Reads the tender** and extracts every requirement with its document, page and text span.
2. **Checks eligibility** against a persistent company knowledge base: **deterministic rules** decide numbers, dates and certificates, and **hybrid retrieval (RAG)** finds the supporting evidence.
3. **Scores the bid** with a weighted policy in which any failed hard gate overrides the score.
4. **Stops for a human** at Gate 1 (the bid decision) and Gate 2 (the drafted response).
5. **Handles corrigenda** on the same tender: it diffs the change, re-runs only the affected checks and shows how the recommendation moved.

### The demo tender in one table

| | **v1**: original tender pack | **v2**: after Corrigendum No. 1 |
|---|---|---|
| Bid deadline | 6 Nov 2026 | **20 Nov 2026** |
| ISO 27001 (valid until 10 Nov) | ✅ Valid, 4 days' margin | ❌ Expires before the deadline |
| Hard gates | 13 checked, none failed | REQ-PQ-06 fails |
| Weighted score | 77.34 | 78.80 |
| **Recommendation** | 🟠 **BID WITH CONDITIONS** | 🔴 **NO BID** |

The score goes up, but the recommendation flips to NO BID. That is the point: **a failed hard gate overrides any score**, and TenderBridge shows exactly why.

### Not a PDF chatbot

| A PDF chatbot | TenderBridge |
|---|---|
| Answers the questions you think to ask | Extracts **every** requirement and checks each one |
| An LLM guesses at dates and amounts | Dates, amounts, thresholds and hard gates are decided **in code** |
| Answers may not say where they came from | Every requirement, verdict and draft claim cites **document, page and span** |
| One chat thread | A **versioned tender workspace** with amendments, re-analysis and comparison |
| No accountability | **Role-based approvals**, version-bound decisions and a full **audit trail** |
| No visibility into the agent | An **AgentOps** dashboard (time, calls, tokens, cost) and **LangSmith** traces |

## ✨ Key features

<table>
<tr>
<td width="50%" valign="top">

**🧠 Agentic analysis**
- Requirement extraction in batches of sections, combining model output with a rules-based extractor so nothing a model skips is lost
- **13 hard gates** checked by deterministic rule tools: turnover with the MSE relaxation, OR-branch similar-work rules, certificate validity on the deadline, personnel, registrations
- A 9-clause commercial risk register compared with the company's approved risk positions
- A weighted bid score: `BID`, `BID_WITH_CONDITIONS` or `NO_BID`

</td>
<td width="50%" valign="top">

**🙋 Human in the loop**
- **Gate 1** (bid decision) and **Gate 2** (draft review) are LangGraph `interrupt()` points with durable checkpoints, so a paused run survives a restart
- Only a Bid Manager or Admin can decide, and refusals are audited
- Decisions are **bound to a tender version**

</td>
</tr>
<tr>
<td valign="top">

**📝 Corrigendum handling**
- Typed changes (Part A amendments, Part B clarifications) with before/after values and the checks each one invalidates
- Preview, then confirm to create a new version
- **Impact re-analysis** re-runs only the affected checks; earlier approvals become `superseded`
- Version comparison: score, recommendation, changed verdicts and terms

</td>
<td valign="top">

**🔗 Cited drafting**
- A response section drafted only from company documents **approved for reuse**
- Every sentence cites numbered evidence, and a verifier checks each claim against its own sources
- Unsupported claims are rewritten or removed, then the section waits at Gate 2
- Approved sections export to DOCX

</td>
</tr>
<tr>
<td valign="top">

**🛡️ Guardrails**
- Prompt-injection screening of visible text, hidden text and PDF metadata, with quarantine
- Role- and sensitivity-filtered retrieval, applied **before** ranking
- PII masked at indexing time; LangSmith traces redacted

</td>
<td valign="top">

**📊 Observability and exports**
- **AgentOps** page: runs, analysis time, LLM calls, tokens, cost per model, per-node latency, eval scores, guardrail events
- Optional **LangSmith** tracing
- Exports: compliance and eligibility XLSX, draft and no-bid DOCX, deadline calendar (ICS), audit JSON

</td>
</tr>
</table>

## 🖼️ Screenshots

<table>
<tr>
<td width="50%"><img src="docs/media/screens/gate1-v1.jpg" alt="Gate 1 with BID WITH CONDITIONS 77.34"><br><sub><b>Gate 1, v1:</b> BID WITH CONDITIONS (77.34), 13 hard gates, waiting for a human decision</sub></td>
<td width="50%"><img src="docs/media/screens/evidence.jpg" alt="Evidence panel for REQ-PQ-06"><br><sub><b>Evidence:</b> REQ-PQ-06 with the tender clause, the rule trace and the company certificates</sub></td>
</tr>
<tr>
<td><img src="docs/media/screens/draft.jpg" alt="Cited response draft"><br><sub><b>Cited draft:</b> every sentence links to an approved company passage</sub></td>
<td><img src="docs/media/screens/corrigendum.jpg" alt="Corrigendum typed changes"><br><sub><b>Corrigendum:</b> typed changes with before/after values and the checks to re-run</sub></td>
</tr>
<tr>
<td><img src="docs/media/screens/versions.jpg" alt="Version comparison"><br><sub><b>Versions:</b> v1 against v2. REQ-PQ-06 goes from Meets to Gap, and contract terms change</sub></td>
<td><img src="docs/media/screens/agentops.jpg" alt="AgentOps dashboard"><br><sub><b>AgentOps:</b> real Claude calls, tokens and cost per model, plus LangSmith</sub></td>
</tr>
</table>

## 🧱 Architecture

```mermaid
flowchart LR
    UI["🖥️ Next.js web UI<br/>dashboard · tender workspace<br/>knowledge base · AgentOps"]
    API["⚡ FastAPI<br/>REST + SSE"]
    subgraph Agents["🧠 LangGraph"]
        AG["Analysis graph<br/>to Gate 1"]
        DG["Drafting graph<br/>to Gate 2"]
    end
    TOOLS["📐 Deterministic tools<br/>rules · scoring · amendment diff"]
    RAG["🔎 Hybrid retrieval<br/>BM25 + vectors, RRF"]
    LLM["🤖 LLM providers<br/>Anthropic · Gemini · Groq"]
    DB[("🗄️ PostgreSQL + pgvector<br/>or SQLite")]
    CK[("💾 Checkpoints")]
    EMB["🧬 BGE-M3 embeddings<br/>local"]
    LS["📈 LangSmith<br/>optional"]

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

    classDef ink fill:#11120D,stroke:#11120D,color:#FDFCF8
    classDef olive fill:#565449,stroke:#565449,color:#FDFCF8
    classDef paper fill:#FDFCF8,stroke:#565449,color:#11120D
    classDef ext fill:#F4F3EE,stroke:#A2A097,color:#11120D,stroke-dasharray:4 3
    class UI,API ink
    class AG,DG,TOOLS,RAG olive
    class DB,CK,EMB paper
    class LLM,LS ext
    style Agents fill:#F4F3EE,stroke:#565449,stroke-width:1.5px,color:#11120D
```

### The agent graphs

**Analysis graph.** It runs in a background thread and streams every node to the UI over SSE.

```mermaid
flowchart LR
    subgraph S1["① Read the tender"]
        direction TB
        A[intake_guard] --> B[load_tender] --> C[shred_requirements] --> D[merge_and_dedupe] --> E[extract_key_facts]
    end
    subgraph S2["② Check and score"]
        direction TB
        F[reconcile_corrigenda] --> G[route_requirements] --> H[eligibility_and_risk] --> I[bid_score]
    end
    S1 --> S2 --> J{{"🙋 gate1_review<br/>human decision"}}
    J -- no bid --> K[write_no_bid_report] --> Z([finalize])
    J -- bid --> Z

    classDef step fill:#565449,stroke:#565449,color:#FDFCF8
    classDef gate fill:#F59E0B,stroke:#B45309,color:#11120D
    classDef nobid fill:#DC2626,stroke:#B91C1C,color:#FFFFFF
    classDef done fill:#11120D,stroke:#11120D,color:#FDFCF8
    class A,B,C,D,E,F,G,H,I step
    class J gate
    class K nobid
    class Z done
    style S1 fill:#F4F3EE,stroke:#A2A097,color:#11120D
    style S2 fill:#F4F3EE,stroke:#A2A097,color:#11120D
```

**Drafting graph.** It starts after a Gate 1 bid approval and works on the saved analysis without re-running it.

```mermaid
flowchart LR
    P[plan_response] --> W[write_sections] --> V[verify_claims]
    V -- unsupported claims --> R[rewrite_failed] --> V
    V -- verified --> G2{{"🙋 gate2_review<br/>approve · edit · request changes · reject"}}
    G2 -- request changes --> W
    G2 --> F([finalize])

    classDef step fill:#565449,stroke:#565449,color:#FDFCF8
    classDef gate fill:#F59E0B,stroke:#B45309,color:#11120D
    classDef done fill:#11120D,stroke:#11120D,color:#FDFCF8
    class P,W,V,R step
    class G2 gate
    class F done
```

### Rules decide, retrieval finds evidence

| Question | Method |
|---|---|
| Is turnover ≥ ₹45 Cr over three years? Is ISO 27001 valid on the deadline? Does a project meet the similar-work OR rule? | 📐 **Deterministic rule tools** over structured company facts (SQL). Authoritative. |
| Which company document supports this requirement? Which approved passage can a draft cite? | 🔎 **Hybrid retrieval**: BM25 + vector search fused with reciprocal rank fusion, filtered by role, sensitivity and reuse approval **before** ranking |
| What does this tender require? What changed in the corrigendum? | 🤖 **LLM extraction** with a rules-based fallback; dates and amounts are diffed in code |

Tender text and company text live in **separate retrieval scopes** and are never mixed.

### State, checkpoints and tracing

- **Checkpoints:** stored in PostgreSQL (`CHECKPOINT_URL`) or a local SQLite file, so a run paused at a gate resumes after a restart. A run interrupted by a restart is recovered on startup.
- **Results:** results, versions, reviews and the audit log are stored with SQLAlchemy and Alembic migrations.
- **Tracing:** every node emits events and audit entries. With LangSmith enabled, traces follow `analysis_run → graph → node → tool / retriever / LLM`, and the Gate 1 resume continues in the same trace thread.

## 🧰 Technology stack

| Layer | Technology | Role |
|---|---|---|
| Agent orchestration | **LangGraph** | Analysis and drafting graphs, `interrupt()` gates, Postgres/SQLite checkpointers |
| LLM access | **LangChain** chat models | Structured output; per-node routing, rate limits, response cache, cost budget |
| LLM providers | **Anthropic** (Claude Haiku 5.5, Sonnet 5.5), **Google Gemini**, **Groq** | Extraction, key-fact gaps, drafting. The app also runs fully offline. |
| Embeddings | **BAAI/bge-m3** (sentence-transformers) | Local 1024-d embeddings; an offline `hash` embedder is the default |
| Backend | **FastAPI**, Pydantic, SQLAlchemy, Alembic | REST API, SSE run events, background runs |
| Database | **PostgreSQL 16 + pgvector** (Docker or Supabase) or **SQLite** | Facts, tenders, versions, chunks and vectors, audit log |
| Documents | PyMuPDF, pypdf, python-docx, openpyxl, Tesseract OCR | PDFs (including scanned pages), DOCX, XLSX |
| Guardrails | Custom checks + Microsoft Presidio (optional) | Injection screening, PII masking, claim and citation verification |
| Observability | **LangSmith** + the AgentOps page | Traces, per-run cost and latency |
| Frontend | **Next.js 15**, React 19, Tailwind CSS 4 | Dashboard, tender workspace, knowledge base, AgentOps |
| Tooling | **uv**, pytest, ruff, mypy | Reproducible environment and checks |

<details>
<summary><b>📁 Repository structure</b></summary>

<br>

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
├── docs/                      # API contract, module interfaces, design decisions, media
├── dev.py                     # cross-platform task runner (Makefile wraps it)
├── docker-compose.yml         # local PostgreSQL 16 + pgvector
├── pyproject.toml · uv.lock   # Python dependencies (managed by uv)
└── .env.example               # configuration template
```

Runtime files (uploads, parsed text, exports, the LLM cache, evaluation reports) go to `storage/`, which is git-ignored.

</details>

## 🚀 Quick start

> [!TIP]
> TenderBridge runs on **macOS, Linux and Windows** with **no API keys**: SQLite, offline embeddings and deterministic stand-ins for the LLMs. Add real models later, under [Configuration](#-configuration).

**Prerequisites**

| Tool | Version | Needed for |
|---|---|---|
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | latest | Everything. uv installs Python 3.13 itself (pinned in `.python-version`). |
| [Git](https://git-scm.com/) | any | Cloning |
| [Node.js](https://nodejs.org/) | 20 or newer (`frontend/.nvmrc` pins 22) | The web UI |
| [Tesseract OCR](https://tesseract-ocr.github.io/) | any | *Optional:* scanned pages (otherwise they index as empty) |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | any | *Optional:* a local PostgreSQL + pgvector |

<details>
<summary>Install uv and Tesseract</summary>

```bash
# uv on macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# uv on Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Tesseract: `brew install tesseract` (macOS), `sudo apt install tesseract-ocr` (Ubuntu), or the [UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki) on Windows (add it to `PATH`).

</details>

**Run it**

```bash
# 1. Clone
git clone https://github.com/harshbhushan21/TenderBridge.git
cd TenderBridge

# 2. Install dependencies into .venv and create .env from .env.example
uv run python dev.py setup

# 3. Check the machine: Python, deps, Node.js, Tesseract, demo-data hashes, .env, database
uv run python dev.py doctor

# 4. Create the tables, seed company facts and index the 52 knowledge-base documents (idempotent)
uv run python dev.py ingest-kb

# 5. Start the API and the web UI together (Ctrl+C stops both)
uv run python dev.py demo
```

Then open **<http://localhost:3000>**. The API docs are at <http://localhost:8000/docs>.

> [!NOTE]
> **No manual virtual environment is needed.** `uv` creates and manages `.venv/` and installs the exact versions in `uv.lock`, and `uv run …` always uses it. To activate it yourself anyway, run `source .venv/bin/activate` (macOS/Linux) or `.venv\Scripts\activate` (Windows). On macOS/Linux, `make <command>` is a shortcut for `uv run python dev.py <command>`.

**Run the servers separately, and verify the install**

```bash
uv run python dev.py api         # FastAPI on http://localhost:8000
uv run python dev.py web         # Next.js on http://localhost:3000 (installs frontend packages on first run)

uv run python dev.py test        # backend tests on a throwaway SQLite database
uv run python dev.py web-check   # frontend typecheck + production build
uv run python dev.py help        # every command
```

## 🔧 Configuration

All settings live in `.env` (git-ignored), and environment variables override it. **Never commit `.env` or real keys.** [`.env.example`](.env.example) documents every variable.

<details open>
<summary><b>🤖 LLM providers: Anthropic, Gemini or Groq</b></summary>

<br>

Without keys, `LLM_FAST=fake:fast` and `LLM_STRONG=fake:strong` run everything offline. Models are called only for **requirement extraction**, **key-fact gap filling**, **drafting** and the **draft rewrite**. Arithmetic, dates, hard gates, scoring, citation checks and exports are always done in code.

Routing per node is defined in [`llm_routing_and_budget.json`](demo_data/demo_config/llm_routing_and_budget.json). For each node, TenderBridge uses the planned primary model if its provider has a key, then the planned fallback, then the `LLM_FAST` / `LLM_STRONG` tier model.

| Node | Primary | Fallback |
|---|---|---|
| Requirement extraction, key-fact gaps | `anthropic:claude-haiku-5-5` | `google_genai:gemini-3.1-flash-lite` |
| Section drafting and rewrite | `anthropic:claude-sonnet-5-5` | `groq:openai/gpt-oss-120b` |

**Option A: Anthropic (Claude).** Used for the demo video. Get a key at [console.anthropic.com](https://console.anthropic.com/) → API keys.

```bash
LLM_FAST=anthropic:claude-haiku-5-5
LLM_STRONG=anthropic:claude-sonnet-5-5
ANTHROPIC_API_KEY=<your-anthropic-key>
MAX_COST_USD=0.50                 # optional per-run cost cap
```

**Option B: Google Gemini and Groq (free tiers).** Keys from [aistudio.google.com/apikey](https://aistudio.google.com/apikey) and [console.groq.com/keys](https://console.groq.com/keys).

```bash
LLM_FAST=google_genai:gemini-3.1-flash-lite
LLM_STRONG=groq:openai/gpt-oss-120b
GOOGLE_API_KEY=<your-gemini-key>  # GEMINI_API_KEY also works
GROQ_API_KEY=<your-groq-key>
```

**Verify** before a demo:

```bash
uv run python dev.py llm-check          # routing, keys, limits, expected calls/tokens/cost per tender (sends nothing)
uv run python dev.py llm-check --ping   # one tiny request per configured model
```

Calls wait for room in each model's per-minute window, a `429` is retried after the provider's suggested delay, and identical inputs are answered from a local cache (`LLM_CACHE=true`; cached calls are free and labelled in AgentOps). `MAX_COST_USD` and `MAX_LLM_CALLS` cap each run.

</details>

<details>
<summary><b>🧬 Hugging Face embeddings (BGE-M3)</b></summary>

<br>

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

</details>

<details>
<summary><b>🗄️ PostgreSQL + pgvector: Docker or Supabase</b></summary>

<br>

SQLite needs no setup. With PostgreSQL + pgvector, vector search runs in SQL.

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
2. In the SQL editor, enable pgvector: `create extension if not exists vector with schema public;`
3. Under **Connect**, copy the **Session pooler** URI (IPv4). The transaction pooler breaks prepared statements, so don't use it.
4. In `.env` (note the two driver prefixes):

```bash
DATABASE_URL=postgresql+psycopg://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
CHECKPOINT_URL=postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

**Then, for either option:**

```bash
uv run python dev.py migrate     # Alembic: tables, pgvector extension, full-text indexes
uv run python dev.py ingest-kb   # seed facts and index the 52 KB documents
```

> [!WARNING]
> Everyone sharing a database must use the same `EMBEDDING_PROVIDER`. `dev.py reset-db` drops all tables, so never run it against a shared database.

</details>

<details>
<summary><b>📈 LangSmith tracing</b></summary>

<br>

1. Create a key at [smith.langchain.com](https://smith.langchain.com/) → **Settings → API Keys**.
2. In `.env`:
   ```bash
   LANGSMITH_TRACING=true
   LANGSMITH_API_KEY=<your-langsmith-key>
   LANGSMITH_PROJECT=tenderbridge
   # LANGSMITH_ENDPOINT=https://eu.api.smith.langchain.com   # only for EU-region accounts
   ```
3. Restart the API and run an analysis. Traces appear in the `tenderbridge` project as `analysis_run → graph → node → tool / retriever / LLM`. Ingestion, amendments, gate decisions, scoring, guardrail events and evaluations are traced too, and the AgentOps page links to LangSmith.

Nothing is sent unless tracing is on **and** a key is set. Inputs and outputs are redacted (emails, phone numbers, PAN/Aadhaar, API keys), and restricted KB text is withheld.

</details>

<details>
<summary><b>📄 Sanitized <code>.env</code> reference</b></summary>

<br>

```bash
# Paths
DEMO_DATA_DIR=demo_data
STORAGE_DIR=storage

# Database (SQLite default; PostgreSQL / Supabase above)
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

</details>

## 🧭 Using TenderBridge

The walkthrough uses the bundled demo tender in `demo_data/tender/TDR-001/original/`. Switch between **Bid Manager** and **Analyst** in the account menu at the top right.

| # | Where | What you do | What you see |
|---|---|---|---|
| 1 | Dashboard, Knowledge base | Review the company KB | 52 documents, structured facts, ISO 27001 expiring on 10 Nov 2026 |
| 2 | New tender | Upload `notice.pdf`, `main_rfp.pdf`, `annexures.pdf`, `price_schedule_boq.xlsx` (keep the corrigendum for later) | Each file validated, screened, parsed and **indexed** |
| 3 | New tender | Click **Analyze** | The progress strip follows each graph node live |
| 4 | Overview | Review Gate 1 | **BID WITH CONDITIONS, 77.34**; 13 hard gates; factor breakdown |
| 5 | Requirements, Risks | Click REQ-PQ-06; open Risks | Clause, page, rule trace and evidence (ISO valid with a 4-day margin); 9-clause risk register |
| 6 | Overview | As Analyst, click **Approve bid**; then as Bid Manager, add a reason and approve | The Analyst is refused and the refusal audited; then **Bid Approved** |
| 7 | Response draft | **Draft the response**, click an `[n]` marker, **Approve**, download | Cited, verified section at Gate 2; DOCX with numbered sources |
| 8 | Documents & corrigenda | Upload `corrigendum.pdf`, **Confirm v2**, **Re-analyse impact** | Typed changes, v1 approval superseded, **NO BID, 78.80** |
| 9 | Versions | Compare v1 and v2 | REQ-PQ-06 goes from Meets to Gap; payment, PBG and SLA-cap terms change |
| 10 | Activity, AgentOps | Review | Full audit trail; runs, time, calls, tokens, cost, per-node latency |

**Roles**

| Role | Can read | Can do |
|---|---|---|
| `analyst` | KB documents tagged for analysts | Upload, analyze, view. **Cannot** decide Gate 1 or approve Gate 2. |
| `writer` | Analyst and writer documents | Edit drafts, request changes |
| `bid_manager` | All KB documents, including risk positions | Everything above, plus Gate 1, Gate 2 and confirming amendments |
| `admin` | Everything | KB ingestion and settings |

Identity comes from demo headers (`X-User`, `X-Role`) set by the role switcher. A production deployment would use real authentication.

**From the command line**

```bash
uv run python dev.py demo-cli CASE-1   # v1 analysis to Gate 1: 77.34 BID_WITH_CONDITIONS
uv run python dev.py demo-cli CASE-2   # v1, then Corrigendum No. 1 and impact re-analysis: 78.80 NO_BID
```

## 🧪 Testing and evaluation

```bash
uv run python dev.py test        # 148 backend tests on a throwaway SQLite database
uv run python dev.py test-pg     # the same tests on PostgreSQL + pgvector (starts Docker)
uv run python dev.py lint        # ruff
uv run python dev.py typecheck   # mypy
uv run python dev.py evals       # full pipeline on TDR-001 in a fresh database, scored against the gold files
uv run python dev.py web-check   # frontend typecheck + production build
```

`dev.py evals` writes `storage/evals/report.json`, and the AgentOps page shows its scores.

**Measured results** from `dev.py evals` on 24 Oct 2026, with BGE-M3 embeddings and the deterministic (no-LLM) extractors:

<table>
<tr>
<td align="center"><h3>100%</h3><sub>mandatory-requirement recall<br>(v1 85/85, v2 89/89)</sub></td>
<td align="center"><h3>0.925</h3><sub>retrieval recall@6<br>(tender 1.00, company 0.85)</sub></td>
<td align="center"><h3>4 / 4</h3><sub>injection traps<br>caught</sub></td>
<td align="center"><h3>6 / 6</h3><sub>bad draft claims<br>struck</sub></td>
<td align="center"><h3>✓</h3><sub>v1 77.34 and v2 78.80<br>reproduced exactly</sub></td>
</tr>
</table>

<details>
<summary>All measured metrics</summary>

| Metric | Result |
|---|---|
| Mandatory-requirement recall | 100% (v1 85/85, v2 89/89 gold items) |
| All-requirement recall | 98.9% |
| Mandatory-flag accuracy | 95.7% (v1), 95.9% (v2) |
| Precision | 25–27%: the extractor favours recall, and the gold set is not exhaustive |
| Assessments | v1 77.34 `BID_WITH_CONDITIONS`, v2 78.80 `NO_BID` |
| Retrieval recall@6 (40 gold questions) | 0.925 (tender 1.00, company 0.85); MRR 0.67 |
| Injection traps caught | 4/4 |
| Claim verifier | 6/6 bad claims struck; 6 of 9 good claims also struck (deterministic checks only) |
| End-to-end time (no LLM calls) | ~78 s: v1 upload and indexing 47 s, v1 analysis 12 s, corrigendum 2 s, v2 impact analysis 13 s |

</details>

**One observed real-model run** (the demo recording, Claude Haiku 5.5 + Sonnet 5.5, empty cache): the v1 analysis, one drafted section and the v2 impact re-analysis together took 9 LLM calls (3 served from cache), about 117k tokens and **$0.049**, as reported by AgentOps. The v1 analysis took about 3 minutes. This is a single run, not a benchmark.

## 🛡️ Security and responsible AI

| | |
|---|---|
| **Untrusted documents** | Every uploaded file and sentence is data. Visible instructions, hidden text and PDF-metadata injections are quarantined, kept out of the index and logged as guardrail events. |
| **Upload validation** | Extension, MIME type, size, archive limits, path traversal and duplicate hashes. |
| **PII masking** | Names (from HR facts) and identifiers (emails, phones, PAN/Aadhaar) are masked when the KB is indexed, so prompts see masked text. Presidio is used when available, regex otherwise. LangSmith traces are redacted separately. |
| **Role-based access** | `allowed_roles`, sensitivity and reuse approval are enforced inside retrieval, before ranking. Risk positions are visible to Bid Managers only. Refusals are audited. |
| **Evidence verification** | Every verdict and draft claim cites a document, page and span. The verifier checks citations, values, negations and expiry, and unsupported claims are removed. |
| **Human control** | No bid decision or draft is final without a Bid Manager at Gate 1 or Gate 2. Decisions are version-bound, and a confirmed amendment supersedes earlier approvals. |
| **Bounded agents** | No agent can submit to a portal, send email or write to the KB. Retries, rewrites, concurrency, calls and cost are capped per run. |
| **Evaluation hygiene** | Gold labels in `demo_data/evaluation/` are evaluator-only and never reach agent context. |

## ⚠️ Limitations

- **Synthetic data:** the tender, the company and the expected results are fictional fixtures created for this demonstration.
- **Focused analysis:** the live analysis checks a focused subset (`ANALYSIS_MODE=focused`), 42 of 105 gold requirements.
- **Demo estimates:** strategic fit, technical capability and delivery capacity are configured demo estimates ([`analysis_inputs.json`](backend/app/agents/analysis_inputs.json)), not computed from documents.
- **Demo identity:** users and roles come from request headers, not an identity provider.
- **Deterministic verifier and screening:** the claim verifier uses deterministic checks only and also strikes some correct claims. Injection screening is heuristic; a model-based screen is planned but not wired.
- **Local files:** uploaded files stay on the machine that received them, so a shared database cannot open another machine's uploads.

## 👥 Team and acknowledgments

Built for **AgentOps 2026: The Agentic Edition** (SDG Club MIT Bengaluru × CGI) · Track 01, Multi-agent systems · Team BR01/MP04 (HX-2SJA)

| Member | Focus |
|---|---|
| **Harsh Bhushan** (team leader), MIT Bengaluru | Agent graph (LangGraph), deterministic rules and scoring, guardrails, LangSmith tracing and evaluations |
| **Swarnim Rai**, MIT Bengaluru | Ingestion and RAG pipeline, facts store, FastAPI backend, web UI |

Built with [LangGraph](https://github.com/langchain-ai/langgraph), [LangChain](https://github.com/langchain-ai/langchain), [LangSmith](https://smith.langchain.com/), [FastAPI](https://fastapi.tiangolo.com/), [Next.js](https://nextjs.org/), [PostgreSQL](https://www.postgresql.org/) + [pgvector](https://github.com/pgvector/pgvector), [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3), [PyMuPDF](https://pymupdf.readthedocs.io/), [Tesseract](https://github.com/tesseract-ocr/tesseract), [Microsoft Presidio](https://microsoft.github.io/presidio/) and [uv](https://docs.astral.sh/uv/). Models from Anthropic, Google and Groq.

**More detail:** [API contract](docs/api_contract.md) · [Module interfaces](docs/interfaces.md) · [Design decisions](docs/decisions.md) · [Demo data pack](demo_data/README.md)

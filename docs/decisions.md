# Design decisions

Short log of choices that keep the code, docs and demo consistent. Add an
entry when a shared contract changes.

| # | Date | Decision | Why |
|---|---|---|---|
| D1 | 23 Oct | Prebuilding is allowed from 23 Oct; the "no code before the event" rule in older planning docs is superseded. | Organiser email, 23 Oct 15:41 IST. |
| D2 | 23 Oct | `docs/api_contract.md` is the single source for API routes. The README links to it instead of repeating route tables. | The old README route table (`/companies/{id}/kb`, `/analyze`, `/approvals`) disagreed with the contract and the final plan. |
| D3 | 23 Oct | Roles are `analyst`, `writer`, `bid_manager`, `admin`. `hr`, `finance`, `legal` are KB data scopes, not login roles. Only `bid_manager` (or `admin`) decides Gate 1, approves Gate 2 and confirms amendments. | The data pack's `allowed_roles` use these names; the code still has `viewer/reviewer` (README task 1.3). The rubric names role-based access, so an analyst being refused at Gate 1 is a demo moment. |
| D4 | 23 Oct | Graph order is `extract_key_facts → reconcile_corrigenda`. | Amendments must override the facts extracted from the base tender. `graph.py` currently runs them the other way round (README task 4.2). |
| D5 | 23 Oct | `finalize` stays as a terminal bookkeeping node after `write_no_bid_report` / `export_outputs`. | Records completion timing; not a business step. |
| D6 | 23 Oct | Model routing: Groq GPT-OSS 20B (fast), GPT-OSS 120B (strong), Gemini 3 Flash (planning + one drafted section), Prompt Guard 2 (injection). Code handles arithmetic, dates, gates, scoring, citation validity and exports. | Matches the free-tier quotas in `llm_routing_and_budget.json`. The routing loader does not yet read that file's `routing` section (README task 4.1). |
| D7 | 23 Oct | SQLite + in-process background threads are the default runtime; Postgres + pgvector, Celery and Redis are optional. | Zero-setup demo and fresh-clone setup are scored (MVP Readiness). |
| D8 | 23 Oct | Eligibility rules live in a config rule pack per procurement regime. | Reusability criterion: a second pack loading without code changes is the reuse proof. |
| D9 | 23 Oct | Contributors are the two team members only. | Team decision. |
| D10 | 23 Oct | Build in strictly sequential phases with one owner each, alternating [S] → [H]. Tasks are grouped by dependency so a phase never needs the other person's unfinished work. | Team decision: avoids both people editing the same area at once, and each phase maps cleanly to a branch merged into `main`. |
| D11 | 23 Oct | Default company ID is `NIMBUS-001`, the ID used by every data-pack file. | The code defaulted to `NIMBUS`, which matched no data. |
| D12 | 23 Oct | Fact seeding rules: `eligible_value_inr` = client-certified bidder share only (never total contract value); project `scope_tags` are factual, not similarity verdicts; every source column is kept in `raw`; person names are stored masked. | Keeps the PRJ-005 trap honest, leaves "similar work" to the rule/judge, avoids schema churn for extra columns (PQ-04 infra turnover), and keeps PII out of prompts by default. |
| D13 | 23 Oct | Postgres runs in Docker (`pgvector/pgvector:0.8.0-pg16`) on host port 5433; schema changes go through Alembic, with `init_db()` kept for zero-setup SQLite. Tests always use their own database (temp SQLite, or `TEST_DATABASE_URL`), never `DATABASE_URL`. | Same database for both of us without touching local installs; 5433 avoids a local Postgres on 5432; tests can no longer wipe dev data. Postgres caught a `varchar(64)` overflow that SQLite ignored, so a column-length test now runs on both. |
| D14 | 23 Oct | Ruff uses an explicit rule set (`E, F, W, I, UP, B`), allowing blind `except` and long lines. | Ruff 0.17's defaults flag the deliberate fail-soft pattern; pinning keeps lint results stable across versions. |
| D15 | 23 Oct | Developer commands live in `dev.py` (stdlib only, run via `uv run`); the Makefile just calls it. `demo_data/` is excluded from line-ending conversion. Relative SQLite paths resolve from the project root. | `make` is missing on Windows; Windows Git can rewrite CRLF/LF and break the manifest hashes; a cwd-relative SQLite path silently created a second empty database when commands ran from another folder. |

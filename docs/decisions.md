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

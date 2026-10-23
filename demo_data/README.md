# TenderBridge demo data pack (`demo_data/`)

Built 22 Oct 2026 for AgentOps 2026 (CGI x MIT Bengaluru, 24 Oct). It follows the folder tree in section 5 and the checklist in section 10 of `TenderBridge_Demo_Data_Strategy.md`, plus the five demo cases in `TenderBridge_LLM_Implementation_Plan.md`. Domain: **IT Infrastructure**.

## Read this first: what is real and what is not

| Part | Status | How it is labelled |
|---|---|---|
| Tender `TDR-001` | **Simulated.** Fictional buyer (DSEDC, "Deccan State"). Clause patterns are modelled on real Indian State Data Centre O&M RFPs (e.g. Gujarat GSDC O&M RFP, GEM/2022/B/2664262, Corrigendum-01) and the GFR/CVC similar-works rule. No text, ID or value is copied. | Red footer on every page: "SIMULATED TENDER ... NOT AN OFFICIAL GOVERNMENT DOCUMENT"; `manifest.json` has `"simulated": true` |
| Bidder Nimbus Digital Services Pvt. Ltd. | **Fictional.** Not CGI, not any real firm. | "SYNTHETIC" footer on every page; financials say "NOT AN ACTUAL AUDIT REPORT"; certificates say "MOCK CERTIFICATION RECORD" |
| Safety traps | Synthetic test fixtures | "SYNTHETIC TEST FIXTURE" footer |
| Metrics | Targets only (e.g. mandatory recall >= 95%) | Nothing in this pack is a measured result |

**Why a simulated tender:** downloads of real tender PDFs were blocked from the build sandbox (proxy 403), and the key demo moments need clauses that line up exactly with the company data (an ISO 27001 expiry that falls between the original and the extended deadline, an OR-style similar-works clause, an MSE relaxation). If you want an authentic second tender for credibility, download the Gujarat GSDC O&M RFP from the link in `tender/TDR-001/manifest.json` (`modelled_on`) on a laptop and add it as `TDR-002` for parsing and recall tests only.

**Say on stage:** "The tender is a realistic simulation of an Indian State Data Centre O&M RFP, the bidder is a fictional company, and every number on screen is computed from those documents."

## The story the data tells

1. **Original RFP (v1, deadline 06-11-2026 15:00):** Nimbus qualifies. Turnover passes only through the MSE relaxation (average Rs. 52.00 Cr vs Rs. 45 Cr for MSEs; Rs. 55 Cr general). Similar works pass through OR-branch (b), not branch (a). ISO/IEC 27001 is valid with a 4-day margin. Expected: **BID_WITH_CONDITIONS**, weighted score 77.34, with conditions (CEO approval for uncapped liability carve-outs, bid-specific OEM MAF).
2. **Corrigendum No. 1 (v2, deadline 20-11-2026 15:00):** the deadline moves past the ISO/IEC 27001 expiry (10-11-2026). Better commercial terms raise the score to 78.8, but the hard gate fails. Expected: **NO_BID**. Pre-bid reply 9 closes the "audit in progress" escape route.
3. **Stress (optional, synthetic Corrigendum No. 2):** MSE relaxation withdrawn, so turnover also fails. Expected: **NO_BID**.

## Folder tree

```
demo_data/
├── README.md                       this file
├── tender/TDR-001/
│   ├── original/
│   │   ├── notice.pdf              NIT, 1 page
│   │   ├── main_rfp.pdf            19 pages: ITB, PQ table, technical evaluation, scope, SLA, GCC, SCC
│   │   ├── annexures.pdf           27 pages: formats PQ-1..10, T-1..7, C-1/2, asset inventory, app list, integrity pact, PBG, contract outline; page 12 is a SCANNED image (OCR trap)
│   │   ├── price_schedule_boq.xlsx price schedule (C-2), manpower rates (C-3), optional items (C-4)
│   │   └── corrigendum.pdf         Corrigendum No. 1 (13 amendments) + 22 pre-bid query responses
│   ├── manifest.json               buyer, ref, versions, precedence, SHA-256 hashes, page counts, modelled_on links
│   └── extracted/tender_sections.json   reference section split (heading, pages, text, live_subset flag) for checking the parser
├── company_kb/                     52 synthetic documents (PDF + DOCX)
│   ├── 01_company/                 company profile, capability statement
│   ├── 02_financials/              3 audit-style statements (Rs. lakh) + CA certificate (Rs. crore, PQ-3 style)
│   ├── 03_certifications/          ISO 9001, ISO/IEC 27001 (expires 10-11-2026), CMMI ML3 records + register (20000-1 and 22301 not held)
│   ├── 04_project_experience/      8 case studies, 4 completion certificates, project register (10 projects)
│   ├── 05_personnel/               10 CVs (6 PDF live, 4 DOCX) + HR certification tracker
│   ├── 06_past_proposals/          2 won, 1 lost (with debrief and NOT-approved-for-reuse sections)
│   ├── 07_policies/                infosec, quality, BC/DR, data protection, delivery and change methodology
│   ├── 08_legal_commercial/        bid and contract risk policy, approval matrix
│   └── 09_registrations/           incorporation, board resolution, non-blacklisting, Udyam (Small), land border, HR headcount, local office template, OEM letter
├── structured_facts/
│   ├── company.json                identity, MSME, offices, headcount, declarations, OEM, insurance (each with evidence span)
│   ├── financials.csv              3 FYs in Rs. crore with source doc, page and exact span
│   ├── certifications.csv          5 rows incl. not-held certs, validity dates, spans
│   ├── projects.csv                10 projects: value, dates, role, share, client-certified value, racks, NOC flag, evidence
│   ├── personnel.csv               10 people: years, domain years, certs with validity/status, availability
│   └── risk_positions.json         10 clause positions + numeric thresholds
├── evaluation/
│   ├── requirements_gold.json      105 labelled requirements (96 mandatory, 39 in tables, 1 scanned, 12 from corrigendum); 42 in the live subset
│   ├── key_facts_gold.json         29 facts with v1 / effective v2 / c2 values and source pages
│   ├── eligibility_gold.json       expected verdicts + computation traces + evidence for v1, v2 and stress X1; bid scores
│   ├── eligibility_rules_gold.json structured rules (field, operator, threshold, window, aggregation, logic) the LLM should extract
│   ├── corrigendum_diff_gold.json  14 changes typed added/changed/removed/superseded/clarified/no_change + calendar expectations
│   ├── retrieval_qa.json           40 questions (20 tender, 20 company) with relevant file/page/span
│   ├── draft_claims_gold.json      a flawed draft section + 15 labelled claims for the verifier
│   ├── validation_report.json      generator self-checks (all spans on stated pages, hashes, labels)
│   └── safety_traps/               injection_test.pdf, corrigendum_test.pdf, scanned_page_test.pdf, kb_poisoned_brochure_test.pdf, traps_manifest.json
└── demo_config/
    ├── company_manifest.json       KB manifest: doc_id, type, dates, sensitivity, roles, synthetic flag, hash, pages, live flag
    ├── bid_scoring_policy.json     hard gates, weights, verdict values, thresholds, override rules
    ├── demo_scenarios.json         CASE-1..5 + X1 with inputs, expected outputs and planned LLM calls
    └── llm_routing_and_budget.json node-to-model routing and quotas from the LLM plan
```

## Demo moments and where the data is

| Moment | What to show | Files |
|---|---|---|
| Mandatory recall live | Extracted requirements vs gold (live subset 42, 40 mandatory) | `evaluation/requirements_gold.json` |
| Complex eligibility | PQ-05: 3 x 15.36 OR 2 x 23.04 OR 1 x 30.72 (Rs. Cr), 7-year window. Branch (a) fails (2 of 3), branch (b) passes. Traps: PRJ-005 total value Rs. 38 Cr must not satisfy (c); PRJ-004 is outside the window; PRJ-009 is high value but not similar | `eligibility_gold.json` → `S-v1.similar_work` |
| MSE relaxation | PQ-02: 52.00 fails Rs. 55 Cr but passes Rs. 45 Cr for a Udyam Small enterprise; values converted from Rs. lakh | `financials.csv`, `company.json` (msme) |
| Corrigendum | Deadline 06-11 → 20-11; ISO/IEC 27001 (expires 10-11) flips to gap; PBG 5→3%, payment 60→45 days, penalty cap 15→10% clear risks; only affected checks re-run | `corrigendum.pdf`, `corrigendum_diff_gold.json`, `S-v2` |
| Score vs hard gate | v2 score goes up (77.34 → 78.8) yet the recommendation is NO_BID | `eligibility_gold.json` bid_assessment |
| Blocked injection | White 1.5 pt text + a visible "note for automated tools" + PDF metadata | `safety_traps/injection_test.pdf`, `traps_manifest.json` |
| Claim verifier | Strikes "CMMI Level 5", "ISO 20000-1", "three State Data Centres", "99.99% uptime", "CISM-certified" (expired), "hold the MAF" | `draft_claims_gold.json` |
| CV vs HR record | NDS-E105's CV lists CISM; HR tracker shows it expired 30-06-2026 → propose NDS-E110 | `personnel.csv`, `05_personnel/staff_certification_tracker.pdf` |

## Section 10 checklist mapping

**A. Authentic tender sources** (simulated, see above)
- [x] Original RFP/NIT: `tender/TDR-001/original/notice.pdf`, `main_rfp.pdf`
- [x] Annexures/forms: `annexures.pdf`, `price_schedule_boq.xlsx`
- [x] Corrigendum: `corrigendum.pdf` (simulated, with pre-bid responses)
- [x] Tender manifest: `tender/TDR-001/manifest.json` (+ `extracted/tender_sections.json`)

**B. Synthetic company KB** (52 documents; strategy recommends 30-35)
- [x] Company profile: `01_company/company_profile.pdf`
- [x] Capability statement: `01_company/service_capabilities.pdf`
- [x] Financial summaries (3): `02_financials/financial_statements_FY2022-23.pdf` ... `FY2024-25.pdf` (+ CA certificate)
- [x] Certification records (3-4): `03_certifications/` (3 mock records + register showing 2 not-held certs)
- [x] Case studies (6-8): `04_project_experience/PRJ-00x_case_study.*` (8; 6 PDF, 2 DOCX)
- [x] Completion records (3-4): `04_project_experience/PRJ-00x_completion_certificate.pdf` (4)
- [x] CVs (8-10): `05_personnel/` (10; 6 live PDFs, 4 DOCX) + HR tracker
- [x] Previous proposals (2-3): `06_past_proposals/` (3 DOCX)
- [x] Policies (4-5): `07_policies/` (5; 3 PDF, 2 DOCX)
- [x] Legal/bid risk positions: `08_legal_commercial/` (2)
- [x] Administrative declarations: `09_registrations/` (8)

**C. Machine-readable facts and configuration**
- [x] KB manifest: `demo_config/company_manifest.json`
- [x] Financial, certification, project, personnel facts: `structured_facts/*.csv`
- [x] Risk positions: `structured_facts/risk_positions.json`
- [x] Bid scoring policy: `demo_config/bid_scoring_policy.json`

**D. Evaluation and demo fixtures**
- [x] Requirements gold: `evaluation/requirements_gold.json`
- [x] Key-facts gold: `evaluation/key_facts_gold.json`
- [x] Eligibility gold: `evaluation/eligibility_gold.json` (+ `eligibility_rules_gold.json`)
- [x] Retrieval QA: `evaluation/retrieval_qa.json` (40)
- [x] Claim verification cases: `evaluation/draft_claims_gold.json` (15)
- [x] Synthetic corrigendum fixture: `evaluation/safety_traps/corrigendum_test.pdf`
- [x] Synthetic injection fixture: `evaluation/safety_traps/injection_test.pdf`
- [x] Demo scenarios/replay: `demo_config/demo_scenarios.json` (saved run references get added on the day)

**Extras from the brief (section 6/19):** scanned-page trap, requirement-in-table trap, poisoned company document, corrigendum diff gold, structured eligibility rules, stale-proposal trap.

## Five demo cases (LLM plan section 3)

| Case | Input | Expected |
|---|---|---|
| CASE-1 Normal qualifying | v1 pack | BID_WITH_CONDITIONS (77.34); one cited section (Format T-1 s.2 and s.4) |
| CASE-2 Expired ISO 27001 | v1 + corrigendum | NO_BID: PQ-06 gap at 20-11-2026 15:00 |
| CASE-3 Corrigendum | add corrigendum | 14 typed changes; dates updated; only affected checks re-run |
| CASE-4 Ambiguous similar work | v1, PQ-05 | PRJ-005 = needs_human; overall still meets via branch (b) |
| CASE-5 Injection + unsupported claims | v1 + injection annex + flawed draft | traps quarantined; 6 claims struck, 1 conditional |
| X1 (optional stress) | + synthetic Corrigendum No. 2 | NO_BID: turnover and ISO both fail |

## Working within the LLM limits (and where we chose realism)

- The pack is realistic in size (19 + 27 + 3 tender pages, about 8,022 words in the main RFP, 52 KB documents). For the live run, process only sections with `live_subset: true` in `tender_sections.json`, the 42 live requirements, and KB docs with `live_subset: true` in `company_manifest.json`. Call it a **focused live analysis**.
- Run the full gold-set evaluation offline the day before and cache it; show cached results labelled as cached.
- Arithmetic, dates, hard gates and scores are all deterministic in the gold files. The LLM's job is extraction, similarity judgement (PRJ-002, PRJ-005, PRJ-009, PRJ-010), technical grading (patching 7 vs 14 days), and drafting.
- Planned calls per case are in `demo_scenarios.json` (`llm_calls_planned`); routing in `llm_routing_and_budget.json`.

## Verdict values

`meets`, `meets_with_undertaking`, `meets_with_substitution`, `needs_action`, `partial`, `needs_human`, `gap` for eligibility; `within_policy`, `review`, `escalate` for contract risks; `BID`, `BID_WITH_CONDITIONS`, `NO_BID` for the recommendation. A `gap` on a hard gate always means `NO_BID`; a human can override only per the approval matrix (KB-LEG-002).

## Honest caveats

- Technical score estimate (72.52) uses assumed marks for approach, transition and presentation (T6-T8). They are labelled assumptions.
- Scoring weights are demo policy choices, not calibrated.
- Outcome figures in case studies (availability, RPO/RTO) are illustrative synthetic numbers and are labelled so.
- Requirement labels were written together with the tender text, so they are exact, but they were not produced by an independent annotator. If time allows, have Harsh spot-check 20 of them.
- `validation_report.json` shows the generator's self-checks (12/12 passed): every gold span is on its stated page, hashes match, every page is labelled, and the old product name never appears.

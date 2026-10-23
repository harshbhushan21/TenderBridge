# TenderBridge API Contract (v1)

> **Status (23 Oct):** contract only. No routes are implemented yet (README Phase 9).

Base URL `http://localhost:8000`. JSON everywhere. Identity headers (demo): `X-User`, `X-Role`
(`analyst|writer|bid_manager|admin`, default `bid_manager`; see `docs/decisions.md` D3).
Permissions: `POST /tenders/{id}/decision`, `POST /drafts/{id}/review` (approve) and
`POST /tenders/{id}/amendments/{aid}/confirm` require `bid_manager` or `admin` and return
403 `permission_denied` (with an audit entry) otherwise. `POST /kb/ingest` requires `admin`.
Retrieval-backed routes filter KB documents by the caller's role. Errors:
`{"error": "<code>", "message": "...", "details": {...}}` with matching HTTP status.

Shapes refer to Pydantic schemas in `backend/app/schemas/*` (`model_dump(mode="json")`).

## Health / settings
| Method | Path | Response |
|---|---|---|
| GET | `/health` | `{status:"ok"}` |
| GET | `/ready` | `{ready, db:{ok,dialect,pgvector?}, llm:{fast,strong,fast_configured,strong_configured}, embeddings:{name,dim}, demo_data:{exists,path}, kb:{status}}` |
| GET | `/settings` | non-secret settings `{analysis_mode, demo_mode, llm, embedding_provider, max_cost_usd, max_llm_calls, company_id}` |

## Knowledge base
| GET | `/kb/status` | `{company_id, name, status, documents, chunks, by_type:{}, facts:{financials,certificates,projects,people,risk_positions}, expiring:[{kind,name,expiry_date,days_left}], warnings:[]}` |
| GET | `/kb/documents?doc_type=&q=` | `{items:[{doc_id, filename, doc_type, page_count, status, sensitivity, approved_for_reuse, live_subset}]}` |
| POST | `/kb/ingest` (admin) body `{force?:bool}` | `{job:"started"}` (background) |
| GET | `/kb/facts/{kind}` kind=`company|financials|certificates|projects|people|risk_positions` | `{items:[...]}` |
| GET | `/kb/search?q=&k=6` | `{items:[RetrievedChunk]}` |

## Tenders
| POST | `/tenders` body `{title, buyer?, reference_no?, analysis_mode?}` | `TenderView` |
| GET | `/tenders` | `{items:[TenderView]}` |
| GET | `/tenders/{id}` | `TenderView` |
| POST | `/tenders/{id}/files` multipart `files[]` (+ optional `doc_role`) | `{files:[{doc_id, filename, doc_role, status}]}` — rejects role `corrigendum` (use amendments) |
| GET | `/tenders/{id}/ingestion?version=` | `{tender_id, status, ready, files:[{doc_id, filename, doc_role, status, status_detail, page_count, flags, version}]}` |
| GET | `/tenders/{id}/files/{doc_id}/pages/{page}` | `{doc_id, page, text, flags}` (evidence viewer) |
| GET | `/tenders/{id}/files/{doc_id}/download` | original file (authorised) |
| POST | `/tenders/{id}/run` body `{version?, analysis_mode?:"focused"|"full"}` | `{analysis_run_id, thread_id, tender_version}` — 409 unless `ready_for_analysis` |
| GET | `/tenders/{id}/runs/{run_id}` | `{run_id, status, current_node, mode, version, error, usage, started_at, finished_at, replay}` |
| GET | `/tenders/{id}/events?run_id=&after_id=` | SSE stream (see below); `?format=json` returns persisted list |
| GET | `/tenders/{id}/requirements?version=&category=&mandatory=&q=` | `{version, analysis_mode, items:[Requirement]}` |
| GET | `/tenders/{id}/key-facts?version=` | `KeyFacts` |
| GET | `/tenders/{id}/compliance?version=` | `{version, items:[ComplianceItem]}` |
| GET | `/tenders/{id}/risks?version=` | `{version, items:[RiskItem]}` |
| GET | `/tenders/{id}/assessment?version=` | `BidAssessment & {approval_status}` |
| POST | `/tenders/{id}/decision` body `GateDecision` | `{status, approval_status}` — resumes Gate 1; 409 if version != current |
| GET | `/tenders/{id}/versions` | `{current_version, versions:[{version, status, amendment_id, confirmed_by, confirmed_at, assessment?:{score,recommendation,approval_status}, run_id}]}` |
| GET | `/tenders/{id}/compare?a=1&b=2` | `{a:{version,score,recommendation,hard_gate_failures}, b:{...}, changed_items:[{requirement_id, before, after}], amendments:[AmendmentChange], derived_impacts:[DerivedImpact]}` |
| GET | `/tenders/{id}/audit` | `{items:[{ts, actor, action, version, target, detail}]}` |
| POST | `/tenders/{id}/ask` body `{question, version?}` | `{answer, citations:[SourceSpan]}` |

## Amendments
| POST | `/tenders/{id}/amendments` multipart `file` | `{amendment_id, doc_id, status, target_version}` |
| GET | `/tenders/{id}/amendments` | `{items:[{amendment_id, status, base_version, target_version, doc_id, created_at}]}` |
| GET | `/tenders/{id}/amendments/{aid}/diff` | `AmendmentDiff & {status}` (409 while parsing) |
| POST | `/tenders/{id}/amendments/{aid}/confirm` body `AmendmentConfirmation` | `{tender_version, status:"reanalysis_required", superseded_reviews:int, stale_drafts:int}` |
| POST | `/tenders/{id}/reanalyse` body `{version?, mode:"impact"}` | `{analysis_run_id, thread_id, tender_version}` |

## Drafts & exports
| GET | `/tenders/{id}/drafts?version=` | `{items:[SectionDraft & {verifier?:VerifierReport}]}` |
| POST | `/drafts/{draft_id}/review` body `DraftReview` | `{status}` — resumes Gate 2 |
| GET | `/tenders/{id}/exports?version=` | `{items:[{export_id, kind, version, created_at}]}` |
| POST | `/tenders/{id}/exports` body `{version?, kinds?}` | `{items:[...]}` (generate on demand) |
| GET | `/tenders/{id}/exports/{kind}?version=` | file download; kinds `compliance_xlsx, eligibility_xlsx, draft_docx, dates_ics, audit_json, no_bid_docx` |

## Ops
| GET | `/ops/metrics?run_id=` | `{run_id, llm:{calls, input_tokens, output_tokens, cost_usd, per_node}, latency_ms_by_node, guardrail_events:[...], node_timings, eval_results?:{...}}` |
| GET | `/ops/guardrails?tender_id=` | `{items:[GuardrailEvent]}` |
| GET | `/ops/runs?tender_id=` | `{items:[run]}` |
| POST | `/ops/runs/{run_id}/cancel` | `{cancelled}` |

### TenderView
```json
{"tenderId":"TDR-…","title":"…","buyer":"…","referenceNo":"…","status":"ready_for_analysis",
 "currentVersion":1,"analysisMode":"focused",
 "ingestionStatus":"ingesting|ready_for_analysis|failed",
 "analysisStatus":"not_started|running|awaiting_human|completed|failed",
 "latestRunId":"RUN-…",
 "latestAssessment":{"version":1,"recommendation":"BID_WITH_CONDITIONS","score":77.34,"hardGateFailures":[]},
 "approvalStatus":"pending|approved|superseded|review_required|rejected",
 "amendmentPending":false,"submissionDeadline":"2026-11-06T15:00:00+05:30","createdAt":"…"}
```
(TenderView is the only camelCase payload; it matches the frontend `TenderView` type.)

### SSE events
`event:` one of `run_started, node_started, node_completed, node_failed, human_review_required, run_completed, run_failed, amendment_diff_ready, budget_exceeded, file_status`; `data:` JSON
`{id, event, tender_id, tender_version, analysis_run_id, node, status, message, payload, ts}`.
Keep-alive comment every 15 s. Client recovers on disconnect via `GET /tenders/{id}/runs/{run_id}` + `?after_id=`.

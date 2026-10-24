"""Cited drafting after Gate 1: plan -> write -> verify (-> rewrite, max 2) -> Gate 2 -> finalize.

Drafting runs as its own graph on the persisted analysis (requirements, compliance, assessment),
so a bid approval never re-runs extraction or eligibility. Every claim carries the KB passages
it came from and is checked by the deterministic verifier before a human sees it.

With an LLM: the routed `write_sections` model returns claims that each cite numbered evidence.
Offline (fake models): an extractive draft made of sentences taken from approved KB passages.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from backend.app.schemas.assessment import (
    ApprovalStatus,
    Claim,
    ClaimVerdict,
    PlannedSection,
    ResponsePlan,
    SectionDraft,
    VerifierReport,
)
from backend.app.schemas.graph_state import TenderState

DRAFT_ROLE = "writer"        # drafts are read by writers and analysts: retrieve only what they may read
EVIDENCE_PER_QUERY = 2
MAX_EVIDENCE = 6
MAX_CLAIMS = 8
MAX_REWRITES = 2             # verifier rounds: one model rewrite, then unsupported claims are removed
MAX_REVISIONS = 2            # Gate 2 "request changes" rounds before the section needs manual work
CITATION_CHARS = 1200

# The one section in scope (Format T-1 §2 and §4), and what to look for in the company KB.
SECTION: dict[str, Any] = {
    "section_key": "T1-2-4",
    "title": "Approach to Data Centre Operations and Security",
    "format_ref": "Format T-1 §2 and §4",
    "kb_queries": [
        "24x7 onsite operations team ITIL service delivery data centre",
        "transition takeover shadowing reverse shadowing readiness review",
        "security patching incident reporting CERT-In information security policy",
        "disaster recovery drills RPO RTO",
        "data residency backups logs kept in India",
    ],
}
_TOPICS = re.compile(r"\b(operat\w*|security|incident|patch\w*|transition|takeover|disaster|drill|"
                     r"backup|monitor\w*|noc|itil|sla|service level)\b", re.I)


class DraftClaimOut(BaseModel):
    text: str = Field(description="One factual sentence of the section")
    sources: list[int] = Field(description="1-based numbers of the evidence passages that support it")


class DraftClaimsOut(BaseModel):
    claims: list[DraftClaimOut]


# --------------------------------------------------------------------------- plan
def plan_response(state: TenderState) -> dict[str, Any]:
    """One section in scope; its requirements are the technical ones it must answer."""
    reqs = [r for r in state.get("requirements", [])
            if not r.get("hard_gate") and _TOPICS.search(str(r.get("text", "")))]
    section = PlannedSection(
        section_key=SECTION["section_key"], title=SECTION["title"], format_ref=SECTION["format_ref"],
        requirement_ids=[r["requirement_id"] for r in reqs][:40],
        kb_queries=list(SECTION["kb_queries"]), max_words=450,
    )
    plan = ResponsePlan(tender_id=state["tender_id"], tender_version=state["tender_version"], sections=[section])
    return {"response_plan": plan.model_dump(mode="json")}


# --------------------------------------------------------------------------- write
def _evidence(company_id: str, queries: list[str]) -> list[Any]:
    """Top approved-for-reuse KB passages for the section, deduplicated, best first."""
    from backend.app.db.engine import session_scope
    from backend.app.retrieval.filters import SearchFilters
    from backend.app.retrieval.keyword import prepare_candidates
    from backend.app.schemas.documents import Scope
    from backend.app.tools.company_search import search_company_kb

    picked: dict[str, Any] = {}
    with session_scope() as session:
        index = prepare_candidates(session, SearchFilters(scope=Scope.kb, company_id=company_id,
                                                          role=DRAFT_ROLE, approved_only=True))
        if not index.rows:
            return []
        for query in queries:
            for hit in search_company_kb(session, company_id, query, k=EVIDENCE_PER_QUERY, role=DRAFT_ROLE,
                                         approved_only=True, candidates=index):
                picked.setdefault(hit.chunk_id, hit)
                if len(picked) >= MAX_EVIDENCE:
                    return list(picked.values())
    return list(picked.values())


def _extractive(evidence: list[Any]) -> DraftClaimsOut:
    """Offline draft: the first substantive sentence of each passage, cited to that passage."""
    from backend.app.agents.nodes.core import _sentences

    claims: list[DraftClaimOut] = []
    seen: list[set[str]] = []
    for i, hit in enumerate(evidence, 1):
        text = str(hit.text)[:CITATION_CHARS]
        sentence = next((s.lstrip("•▪-–* ").strip() for s in _sentences(text)
                         if len(s.split()) >= 8 and not s.rstrip().endswith(":")), None)
        if not sentence:
            continue
        words = set(re.findall(r"[a-z0-9]+", sentence.lower()))
        if any(len(words & w) / len(words | w) > 0.5 for w in seen):  # same fact from another document
            continue
        seen.append(words)
        claims.append(DraftClaimOut(text=sentence, sources=[i]))
    return DraftClaimsOut(claims=claims[:MAX_CLAIMS])


def _claims_from(out: DraftClaimsOut, evidence: list[Any], draft_id: str, start: int = 1) -> list[Claim]:
    spans = [h.to_span(max_len=CITATION_CHARS) for h in evidence]
    claims: list[Claim] = []
    for n, c in enumerate(out.claims[:MAX_CLAIMS], start):
        cited = [spans[i - 1] for i in dict.fromkeys(c.sources) if 1 <= i <= len(spans)]
        if c.text.strip() and cited:  # a claim without a valid source is never kept
            claims.append(Claim(claim_id=f"{draft_id}-C{n}", text=c.text.strip(), citations=cited))
    return claims


def render_body(claims: list[Claim]) -> str:
    """Prose with [n] markers; n numbers sources in first-use order (as in the DOCX source list)."""
    order: dict[tuple, int] = {}
    parts = []
    for claim in claims:
        marks = []
        for s in claim.citations:
            key = (s.doc_id, s.page, s.text_span[:60])
            order.setdefault(key, len(order) + 1)
            marks.append(order[key])
        parts.append(f"{claim.text} [{', '.join(str(m) for m in dict.fromkeys(marks))}]")
    return " ".join(parts)


def _brief(state: TenderState, section: dict[str, Any], evidence: list[Any], feedback: str | None) -> str:
    from backend.app.guardrails.injection import wrap_untrusted

    reqs = {r["requirement_id"]: r for r in state.get("requirements", [])}
    asks = [str(reqs[rid].get("text", ""))[:200] for rid in section.get("requirement_ids", [])[:12] if rid in reqs]
    numbered = "\n\n".join(f"[{i}] ({h.doc_id} p.{h.page}) {str(h.text)[:CITATION_CHARS]}"
                           for i, h in enumerate(evidence, 1))
    return (f"Section: {section['title']} ({section.get('format_ref')}), at most {section.get('max_words', 450)} words.\n"
            f"Tender requirements this section should answer:\n- " + "\n- ".join(asks or ["(none extracted)"]) +
            (f"\n\nReviewer feedback to address:\n{feedback}" if feedback else "") +
            "\n\nApproved company evidence (cite by number):\n" + wrap_untrusted(numbered, "company KB"))


def write_sections(state: TenderState) -> dict[str, Any]:
    from backend.app.llm.factory import load_prompt, structured_call

    plan = state.get("response_plan") or {}
    existing = {d["section_key"]: d for d in state.get("drafts", [])}
    drafts = []
    for section in plan.get("sections", []):
        prior = existing.get(section["section_key"]) or {}
        review = (state.get("gate2_reviews") or {}).get(section["section_key"]) or {}
        revising = review.get("action") == "request_changes"
        revision = int(prior.get("revision", -1)) + 1 if prior else 0
        draft_id = f"{state['analysis_run_id']}-{section['section_key']}"
        evidence = _evidence(state["company_id"], section.get("kb_queries") or [section["title"]])
        if not evidence:
            draft = SectionDraft(draft_id=draft_id, tender_id=state["tender_id"],
                                 tender_version=state["tender_version"], section_key=section["section_key"],
                                 title=section["title"], body_markdown="", revision=revision,
                                 placeholders=["No approved company evidence was found for this section."])
            drafts.append({**draft.model_dump(mode="json"), "generated_by": "none", "evidence_count": 0})
            continue
        result = structured_call("write_sections", DraftClaimsOut, system=load_prompt("write_sections"),
                                 user=_brief(state, section, evidence, review.get("comment") if revising else None),
                                 heuristic=lambda ev=evidence: _extractive(ev))
        claims = _claims_from(result.value, evidence, draft_id)
        if not claims and not result.fallback:  # model cited nothing usable: fall back to extraction
            claims = _claims_from(_extractive(evidence), evidence, draft_id)
        draft = SectionDraft(draft_id=draft_id, tender_id=state["tender_id"], tender_version=state["tender_version"],
                             section_key=section["section_key"], title=section["title"],
                             body_markdown=render_body(claims), claims=claims, revision=revision)
        drafts.append({**draft.model_dump(mode="json"), "evidence_count": len(evidence),
                       "generated_by": "extractive (no model configured)" if result.fallback else result.model,
                       "removed_claims": []})
    return {"drafts": drafts, "rewrite_counts": {d["draft_id"]: 0 for d in drafts}}


# --------------------------------------------------------------------------- verify / rewrite
def verify_claims(state: TenderState) -> dict[str, Any]:
    """Deterministic check of every claim against its own cited passages."""
    from backend.app.guardrails.claim_verifier import STRUCK, verify_claim

    reports = []
    for draft in state.get("drafts", []):
        verdicts = []
        for claim in draft.get("claims", []):
            evidence = " ".join(str(c.get("text_span", "")) for c in claim.get("citations", []))
            checked = verify_claim({"claim_id": claim["claim_id"], "text": claim["text"],
                                    "citations": claim.get("citations", [])}, evidence)
            verdicts.append(ClaimVerdict(claim_id=checked.claim_id, verdict=checked.verdict,
                                         reason=checked.reason, evidence=claim.get("citations", [])))
        failed = [v for v in verdicts if v.verdict in STRUCK]
        reports.append(VerifierReport(
            draft_id=draft["draft_id"], revision=int(draft.get("revision", 0)), verdicts=verdicts,
            passed=not failed and bool(draft.get("claims")),
            feedback="; ".join(f"{v.claim_id}: {v.reason}" for v in failed),
        ).model_dump(mode="json"))
    return {"verifier_reports": reports}


def needs_rewrite(state: TenderState) -> bool:
    counts = state.get("rewrite_counts") or {}
    for report in state.get("verifier_reports", []):
        failed = [v for v in report.get("verdicts", []) if v.get("verdict") in ("unsupported", "contradicted")]
        if failed and int(counts.get(report["draft_id"], 0)) < MAX_REWRITES:
            return True
    return False


def rewrite_failed(state: TenderState) -> dict[str, Any]:
    """Round 1 (model configured): rewrite only the failed claims from their evidence.
    Otherwise, or on the last round: remove them and leave a visible placeholder."""
    from backend.app.llm.factory import is_fake, load_prompt, resolve, structured_call

    reports = {r["draft_id"]: r for r in state.get("verifier_reports", [])}
    counts = dict(state.get("rewrite_counts") or {})
    drafts = []
    for draft in state.get("drafts", []):
        verdicts = {v["claim_id"]: v for v in (reports.get(draft["draft_id"]) or {}).get("verdicts", [])}
        failed = [c for c in draft.get("claims", [])
                  if verdicts.get(c["claim_id"], {}).get("verdict") in ("unsupported", "contradicted")]
        if not failed:
            drafts.append(draft)
            continue
        round_no = int(counts.get(draft["draft_id"], 0)) + 1
        counts[draft["draft_id"]] = round_no
        kept = [c for c in draft["claims"] if c not in failed]
        rewritten: list[dict[str, Any]] = []
        if round_no == 1 and not is_fake(resolve("rewrite_failed").model):
            evidence = [c for claim in failed for c in claim.get("citations", [])]
            numbered = "\n\n".join(f"[{i}] {c.get('text_span', '')}" for i, c in enumerate(evidence, 1))
            asks = "\n".join(f"- {c['text']}  (verifier: {verdicts[c['claim_id']]['reason']})" for c in failed)
            out = structured_call("rewrite_failed", DraftClaimsOut, system=load_prompt("write_sections"),
                                  user=f"Rewrite these claims so the evidence fully supports them, or drop them:\n"
                                       f"{asks}\n\nEvidence (cite by number):\n{numbered}",
                                  heuristic=lambda: DraftClaimsOut(claims=[]))
            from backend.app.schemas.documents import SourceSpan
            spans = [SourceSpan.model_validate(e) for e in evidence]
            for n, c in enumerate(out.value.claims[:len(failed)], 1):
                cited = [spans[i - 1] for i in dict.fromkeys(c.sources) if 1 <= i <= len(spans)]
                if c.text.strip() and cited:
                    rewritten.append(Claim(claim_id=f"{draft['draft_id']}-R{round_no}-{n}", text=c.text.strip(),
                                           citations=cited).model_dump(mode="json"))
        removed = [] if rewritten else [{"text": c["text"], "reason": verdicts[c["claim_id"]]["reason"]}
                                        for c in failed]
        claims = [Claim.model_validate(c) for c in kept + rewritten]
        placeholders = list(draft.get("placeholders", []))
        if removed:
            placeholders.append(f"{len(removed)} statement(s) removed by the verifier: add approved evidence "
                                "or confirm them manually.")
        drafts.append({**draft, "claims": [c.model_dump(mode="json") for c in claims],
                       "body_markdown": render_body(claims), "placeholders": placeholders,
                       "removed_claims": [*draft.get("removed_claims", []), *removed]})
    return {"drafts": drafts, "rewrite_counts": counts}


# --------------------------------------------------------------------------- Gate 2
def gate2_review(state: TenderState) -> dict[str, Any]:
    """Pause until a bid manager approves, edits, rejects or asks for changes; the decision is
    applied to the draft here so it is persisted with the run."""
    from langgraph.types import interrupt

    draft = next(iter(state.get("drafts", [])), None)
    if draft is None:
        return {}
    report = next((r for r in state.get("verifier_reports", []) if r.get("draft_id") == draft["draft_id"]), None)
    decision = interrupt({"gate": "gate2", "tender_id": state["tender_id"],
                          "tender_version": state["tender_version"], "draft_id": draft["draft_id"],
                          "revision": draft.get("revision", 0), "verifier_report": report,
                          "message": "Approve, edit, reject or request changes for this section."})
    action = decision.get("action")
    updated = dict(draft)
    if action == "approve":
        updated["status"] = ApprovalStatus.approved.value
    elif action == "edit":
        updated.update(status=ApprovalStatus.approved.value, body_markdown=decision.get("edited_markdown") or "",
                       human_edited=True)
    elif action == "reject":
        updated["status"] = ApprovalStatus.rejected.value
    elif action == "request_changes":
        updated["status"] = (ApprovalStatus.pending.value if int(draft.get("revision", 0)) < MAX_REVISIONS
                             else ApprovalStatus.review_required.value)
    updated["review"] = {k: decision.get(k) for k in ("action", "reviewer", "comment")}
    return {"drafts": [updated], "gate2_reviews": {draft["section_key"]: decision}}


def after_gate2(state: TenderState) -> str:
    draft = next(iter(state.get("drafts", [])), {})
    review = (state.get("gate2_reviews") or {}).get(draft.get("section_key", ""), {})
    if review.get("action") == "request_changes" and draft.get("status") == ApprovalStatus.pending.value:
        return "write_sections"
    return "finalize"

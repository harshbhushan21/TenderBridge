"""Bounded graph nodes for TenderBridge analysis.

Nodes exchange only JSON-compatible values through :class:`TenderState`.  The
deterministic nodes are intentionally usable without an LLM so that eligibility
and scoring remain reproducible and testable.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from backend.app.schemas.assessment import (
    BidAssessment,
    BidScoringPolicy,
    CriterionScore,
    HardGateResult,
    Recommendation,
)
from backend.app.schemas.eligibility import (
    ComplianceItem,
    EligibilityRule,
    EligibilityStatus,
    RiskItem,
    RiskLevel,
)
from backend.app.schemas.graph_state import TenderState, dump
from backend.app.schemas.requirements import ExtractedRequirement, KeyFacts, RequirementCategory
from backend.app.tools.certificate_rules import check_certification
from backend.app.tools.facts import (
    get_certificates,
    get_company,
    get_financials,
)
from backend.app.tools.financial_rules import check_net_worth, check_turnover


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _source(section: dict[str, Any], text: str = "") -> dict[str, Any]:
    return {
        "doc_id": section.get("doc_id", "unknown"),
        "page": section.get("page_start"),
        "section_path": section.get("section_path"),
        "text_span": text[:400],
        "tender_version": section.get("tender_version"),
    }


def intake_guard(state: TenderState) -> dict[str, Any]:
    """Reject incomplete or quarantined input before any analysis work."""
    required = ("tender_id", "tender_version", "analysis_run_id")
    missing = [key for key in required if not state.get(key)]
    sections = state.get("sections") or []
    flags = state.get("flags") or []
    critical = [
        f for f in flags
        if f.get("severity") == "critical" and f.get("quarantined", True)
    ]
    if missing:
        return {"intake_ok": False, "stop_reason": f"Missing graph fields: {', '.join(missing)}"}
    if not sections:
        return {"intake_ok": False, "stop_reason": "No parsed tender sections are available"}
    if critical:
        return {
            "intake_ok": False,
            "stop_reason": "Critical quarantined content requires review before analysis",
        }
    return {"intake_ok": True, "stop_reason": None}


def load_tender(state: TenderState) -> dict[str, Any]:
    if not state.get("intake_ok", False):
        return {}
    version = state["tender_version"]
    sections = [
        {**section, "tender_version": section.get("tender_version", version)}
        for section in state.get("sections", [])
    ]
    return {"sections": sections}


def shred_requirements(state: TenderState) -> dict[str, Any]:
    """Extract conservative requirement candidates from parsed sections.

    This is a safe fallback for environments without a configured LLM.  It
    never invents a clause: callers may replace this node with a structured
    model node while retaining the same output contract.
    """
    extracted: list[dict[str, Any]] = []
    for section in state.get("sections", []):
        text = str(section.get("text", "")).strip()
        if not text:
            continue
        sentences = [s.strip() for s in re.split(r"(?<=[.;])\s+|\n+", text) if s.strip()]
        for index, sentence in enumerate(sentences):
            if not re.search(r"\b(shall|must|required|eligible|minimum|valid|submit)\b", sentence, re.I):
                continue
            clause = section.get("clause_ref") or f"{section.get('section_id', 'section')}-{index + 1}"
            category = RequirementCategory.other
            lower = sentence.lower()
            for token, candidate in (
                ("turnover", RequirementCategory.eligibility_financial),
                ("net worth", RequirementCategory.eligibility_financial),
                ("experience", RequirementCategory.eligibility_experience),
                ("similar work", RequirementCategory.eligibility_experience),
                ("iso", RequirementCategory.eligibility_certification),
                ("certificate", RequirementCategory.eligibility_certification),
                ("personnel", RequirementCategory.personnel),
                ("payment", RequirementCategory.commercial),
                ("penalty", RequirementCategory.commercial),
                ("submission", RequirementCategory.submission),
            ):
                if token in lower:
                    category = candidate
                    break
            item = ExtractedRequirement(
                clause_ref=str(clause),
                title=str(section.get("title", "")),
                text=sentence,
                category=category,
                mandatory=bool(re.search(r"\b(shall|must|required)\b", sentence, re.I)),
                page=section.get("page_start"),
                quote=sentence[:400],
                confidence=0.65,
            )
            extracted.append({
                **item.model_dump(mode="json"),
                "source": _source(section, sentence),
                "section_path": section.get("section_path"),
                "hard_gate": category.value.startswith("eligibility_"),
                "tender_id": state["tender_id"],
                "tender_version": state["tender_version"],
            })
    return {"raw_requirements": extracted}


def merge_and_dedupe(state: TenderState) -> dict[str, Any]:
    requirements: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], str] = {}
    for index, raw in enumerate(state.get("raw_requirements", [])):
        text = str(raw.get("text", "")).strip()
        key = (str(raw.get("clause_ref") or ""), re.sub(r"\W+", " ", text.lower()).strip())
        if key in seen:
            continue
        requirement_id = f"REQ-{raw.get('clause_ref') or index + 1}"
        if requirement_id in {r["requirement_id"] for r in requirements}:
            requirement_id = f"{requirement_id}-{index + 1}"
        seen[key] = requirement_id
        requirements.append({
            "requirement_id": requirement_id,
            "tender_id": state["tender_id"],
            "tender_version": state["tender_version"],
            "clause_ref": raw.get("clause_ref"),
            "title": raw.get("title", ""),
            "text": text,
            "category": raw.get("category", RequirementCategory.other.value),
            "modality": raw.get("modality", "shall"),
            "mandatory": raw.get("mandatory", True),
            "hard_gate": raw.get("hard_gate", False),
            "section_path": raw.get("section_path"),
            "source": raw.get("source", _source(raw)),
            "confidence": raw.get("confidence", 0.65),
            "needs_review": raw.get("confidence", 0.65) < 0.7,
            "parsed_rule": raw.get("parsed_rule"),
        })
    return {"requirements": requirements}


def extract_key_facts(state: TenderState) -> dict[str, Any]:
    """Validate caller/parser facts and preserve missing values explicitly."""
    facts = state.get("key_facts")
    if facts:
        validated = KeyFacts.model_validate(facts)
    else:
        validated = KeyFacts(
            tender_id=state["tender_id"],
            tender_version=state["tender_version"],
            missing=["submission_deadline", "company_facts"],
        )
    return {"key_facts": dump(validated)}


def route_requirements(state: TenderState) -> dict[str, Any]:
    routed = []
    for item in state.get("requirements", []):
        routed.append({
            "requirement_id": item["requirement_id"],
            "category": item.get("category", "other"),
            "rule_kind": (item.get("parsed_rule") or {}).get("kind"),
        })
    return {"derived_impacts": routed}


def eligibility_and_risk(state: TenderState) -> dict[str, Any]:
    """Evaluate rules using SQL-backed facts when a session is supplied."""
    session = state.get("_session")
    company_id = state.get("company_id")
    key_facts = KeyFacts.model_validate(state["key_facts"]) if state.get("key_facts") else None
    compliance: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    if session is None or not company_id:
        for req in state.get("requirements", []):
            compliance.append(ComplianceItem(
                requirement_id=req["requirement_id"], tender_id=state["tender_id"],
                tender_version=state["tender_version"], category=req.get("category", "other"),
                mandatory=req.get("mandatory", True), hard_gate=req.get("hard_gate", False),
                status=EligibilityStatus.needs_human,
                summary="Company facts/session are unavailable; manual verification is required.",
                tender_source=req["source"], confidence=0.0, checked_by="human",
            ).model_dump(mode="json"))
        return {"compliance": compliance, "risks": risks}

    company = get_company(session, company_id)
    financials = get_financials(session, company_id)
    certificates = get_certificates(session, company_id)
    for req in state.get("requirements", []):
        result = None
        raw_rule = req.get("parsed_rule")
        if raw_rule:
            try:
                from pydantic import TypeAdapter
                parsed = TypeAdapter(EligibilityRule).validate_python(raw_rule)
                if parsed.kind == "turnover":
                    result = check_turnover(financials, parsed, company)
                elif parsed.kind == "net_worth":
                    result = check_net_worth(financials, parsed)
                elif parsed.kind == "certification":
                    result = check_certification(certificates, parsed, key_facts)
            except (TypeError, ValueError):
                result = None
        status = result.status if result else EligibilityStatus.needs_human
        summary = result.summary if result else "No machine-checkable rule is available."
        item = ComplianceItem(
            requirement_id=req["requirement_id"], tender_id=state["tender_id"],
            tender_version=state["tender_version"], category=req.get("category", "other"),
            mandatory=req.get("mandatory", True), hard_gate=req.get("hard_gate", False),
            status=status, summary=summary, rule_result=result,
            tender_source=req["source"], company_evidence=result.evidence if result else [],
            actions=result.actions if result else ["Assign an owner for manual verification"],
            confidence=req.get("confidence", 0.65), checked_by="rule" if result else "human",
        )
        compliance.append(item.model_dump(mode="json"))
        if status in (EligibilityStatus.gap, EligibilityStatus.needs_human):
            risks.append(RiskItem(
                risk_id=f"RISK-{req['requirement_id']}", requirement_id=req["requirement_id"],
                tender_id=state["tender_id"], tender_version=state["tender_version"],
                category=req.get("category", "other"), level=RiskLevel.escalate if req.get("hard_gate") else RiskLevel.review,
                tender_value=summary, policy_value="Manual review required", summary=summary,
                source=req["source"],
            ).model_dump(mode="json"))
    return {"compliance": compliance, "risks": risks}


def bid_score(state: TenderState) -> dict[str, Any]:
    policy = BidScoringPolicy.model_validate(state.get("scoring_policy") or {})
    compliance = [ComplianceItem.model_validate(i) for i in state.get("compliance", [])]
    hard = [
        HardGateResult(requirement_id=i.requirement_id, label=i.requirement_id,
                       status=i.status.value, passed=i.status.passing,
                       summary=i.summary, evidence=i.company_evidence)
        for i in compliance if i.hard_gate
    ]
    failures = [h.requirement_id for h in hard if not h.passed]
    statuses = [i.status.value for i in compliance]
    eligibility = sum(policy.status_points.get(s, 50.0) for s in statuses) / len(statuses) if statuses else 0.0
    risk_items = [RiskItem.model_validate(i) for i in state.get("risks", [])]
    risk_score = sum(policy.risk_level_points.get(i.level.value, 20.0) for i in risk_items) / len(risk_items) if risk_items else 100.0
    score = round((eligibility * 0.7) + (risk_score * 0.3), policy.rounding)
    if failures:
        recommendation = Recommendation.NO_BID
    elif score >= policy.bid_threshold:
        recommendation = Recommendation.BID
    elif score >= policy.conditional_threshold:
        recommendation = Recommendation.BID_WITH_CONDITIONS
    else:
        recommendation = Recommendation.NO_BID
    assessment = BidAssessment(
        tender_id=state["tender_id"], tender_version=state["tender_version"],
        analysis_run_id=state["analysis_run_id"], score=score,
        recommendation=recommendation, hard_gates=hard, hard_gate_failures=failures,
        conditions=[i.summary for i in compliance if i.status.value in policy.conditional_statuses],
        top_risks=[i.summary for i in risk_items[:5]],
        narrative="Mandatory hard gates override the weighted score." if failures else "",
        policy_version=policy.version, analysis_mode=state.get("analysis_mode", "focused"),
        created_at=datetime.now(UTC),
        criteria=[
            CriterionScore(key="eligibility_strength", label="Eligibility strength", weight=.7,
                           raw_score=round(eligibility, 2), weighted=round(eligibility * .7, 2)),
            CriterionScore(key="commercial_risk", label="Risk posture", weight=.3,
                           raw_score=round(risk_score, 2), weighted=round(risk_score * .3, 2)),
        ],
    )
    return {"assessment": assessment.model_dump(mode="json")}


def write_no_bid_report(state: TenderState) -> dict[str, Any]:
    assessment = state.get("assessment") or {}
    return {"no_bid_report": {
        "tender_id": state.get("tender_id"), "version": state.get("tender_version"),
        "recommendation": assessment.get("recommendation", Recommendation.NO_BID.value),
        "score": assessment.get("score", 0), "hard_gate_failures": assessment.get("hard_gate_failures", []),
        "reasons": assessment.get("top_risks", []),
    }}


def reconcile_corrigenda(state: TenderState) -> dict[str, Any]:
    """Keep amendment metadata explicit; no amendment is silently applied."""
    changes = state.get("change_map") or {}
    invalidated = sorted(changes)
    return {
        "invalidated_checks": invalidated,
        "reusable_checks": [] if invalidated else [i["requirement_id"] for i in state.get("requirements", [])],
    }


def plan_response(state: TenderState) -> dict[str, Any]:
    """Create a traceable response outline without inventing section content."""
    from backend.app.schemas.assessment import PlannedSection, ResponsePlan

    grouped: dict[str, list[str]] = {}
    for requirement in state.get("requirements", []):
        grouped.setdefault(requirement.get("section_path") or "Unmapped", []).append(
            requirement["requirement_id"]
        )
    sections = [
        PlannedSection(section_key=f"SEC-{index}", title=title, requirement_ids=req_ids)
        for index, (title, req_ids) in enumerate(grouped.items(), 1)
    ]
    plan = ResponsePlan(
        tender_id=state["tender_id"], tender_version=state["tender_version"],
        sections=sections,
        unmapped_requirement_ids=[] if sections else [r["requirement_id"] for r in state.get("requirements", [])],
    )
    return {"response_plan": plan.model_dump(mode="json")}


def write_sections(state: TenderState) -> dict[str, Any]:
    """Produce evidence-safe draft shells; unsupported claims become placeholders."""
    from backend.app.schemas.assessment import SectionDraft

    plan = state.get("response_plan") or {}
    drafts = []
    for section in plan.get("sections", []):
        draft = SectionDraft(
            draft_id=f"{state['analysis_run_id']}-{section['section_key']}",
            tender_id=state["tender_id"], tender_version=state["tender_version"],
            section_key=section["section_key"], title=section["title"],
            body_markdown="<!-- Draft requires approved company evidence. -->",
            placeholders=["Attach approved evidence for: " + ", ".join(section["requirement_ids"])],
        )
        drafts.append({
            **draft.model_dump(mode="json"),
            "requirement_ids": section["requirement_ids"],
        })
    return {"drafts": drafts}


def verify_claims(state: TenderState) -> dict[str, Any]:
    """Reject draft claims without citations instead of fabricating support."""
    from backend.app.schemas.assessment import ClaimVerdict, VerifierReport

    reports = []
    for draft_data in state.get("drafts", []):
        verdicts = [
            ClaimVerdict(
                claim_id=claim["claim_id"],
                verdict="unverifiable" if not claim.get("citations") else "supported",
                reason="No source citation was attached." if not claim.get("citations") else "Citation attached.",
                evidence=claim.get("citations", []),
            )
            for claim in draft_data.get("claims", [])
        ]
        report = VerifierReport(
            draft_id=draft_data["draft_id"], revision=draft_data.get("revision", 0),
            verdicts=verdicts,
            passed=not any(v.verdict in ("unsupported", "contradicted") for v in verdicts),
            feedback="Claims without citations require evidence before approval.",
        )
        reports.append(report.model_dump(mode="json"))
    return {"verifier_reports": reports}


def final_compliance_check(state: TenderState) -> dict[str, Any]:
    """Map every mandatory requirement to a draft or report a concrete gap."""
    draft_ids = {
        req_id
        for draft in state.get("drafts", [])
        for req_id in (draft.get("requirement_ids") or [])
    }
    gaps = [
        {"requirement_id": req["requirement_id"], "reason": "No approved draft mapping", "severity": "high"}
        for req in state.get("requirements", [])
        if req.get("mandatory") and req["requirement_id"] not in draft_ids
    ]
    return {"compliance_gaps": gaps}


def human_gate_1(state: TenderState) -> dict[str, Any]:
    """Require an explicit version-bound reviewer decision; never auto-approve."""
    decision = state.get("gate1_decision")
    if not decision:
        return {"errors": ["Gate 1 requires reviewer decision for this tender version"]}
    if decision.get("tender_version") != state.get("tender_version"):
        return {"errors": ["Gate 1 decision belongs to a different tender version"]}
    return {}


def human_gate_2(state: TenderState) -> dict[str, Any]:
    """Validate section review actions before export."""
    reviews = state.get("gate2_reviews") or {}
    pending = [
        draft.get("section_key") for draft in state.get("drafts", [])
        if draft.get("section_key") not in reviews
    ]
    return {"errors": [f"Gate 2 review missing for {key}" for key in pending]}


def finalize(state: TenderState) -> dict[str, Any]:
    return {"node_timings": {**state.get("node_timings", {}), "completed": _now()}}

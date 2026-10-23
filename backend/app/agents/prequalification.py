"""Pre-qualification (hard-gate) clauses: extraction, routing and evaluation.

The PQ table is where a bid is won or disqualified, so it gets a dedicated,
deterministic path: each PQ row (and the single-entity clause) becomes one
hard-gate requirement, is routed by its content to a Phase 2 rule tool, and is
evaluated against the SQL facts. Thresholds, windows and dates come from the
tender text and key facts, never from constants. An LLM can propose the same
`check` labels; the evaluation stays in code.
"""
from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.schemas.documents import Scope, SourceSpan
from backend.app.schemas.eligibility import (
    Calculation,
    CertificationRule,
    CompanyProfile,
    DocumentPresenceRule,
    EligibilityStatus,
    NetWorthRule,
    RuleResult,
    SimilarWorkBranch,
    SimilarWorkRule,
    TurnoverRule,
)
from backend.app.schemas.requirements import KeyFacts, RequirementCategory
from backend.app.tools.certificate_rules import find_standards, normalize_standard
from backend.app.tools.date_normalization import (
    parse_all_money,
    parse_date,
    word_to_int,
    years_between,
)
from backend.app.tools.facts import get_certificates, get_company, get_financials, get_projects
from backend.app.tools.financial_rules import check_net_worth, check_turnover
from backend.app.tools.project_rules import check_similar_work
from backend.app.tools.registration_rules import check_registration
from backend.app.tools.rule_parser import parse_requirement

_PQ_MARK = re.compile(r"^\s*(PQ-\d{2})\s*$", re.MULTILINE)
_SINGLE_ENTITY = re.compile(r"(?:(\d+\.\d+\.\d+)\s+)?(Bids from a consortium or joint venture shall not be "
                            r"accepted\.[^.]*\.)", re.IGNORECASE)
_INPUTS = Path(__file__).with_name("analysis_inputs.json")

# check -> requirement category
CHECK_CATEGORY: dict[str, RequirementCategory] = {
    "company_age": RequirementCategory.eligibility_registration,
    "single_entity": RequirementCategory.eligibility_registration,
    "turnover": RequirementCategory.eligibility_financial,
    "segment_turnover": RequirementCategory.eligibility_financial,
    "net_worth": RequirementCategory.eligibility_financial,
    "similar_work": RequirementCategory.eligibility_experience,
    "certifications": RequirementCategory.eligibility_certification,
    "tech_staff": RequirementCategory.eligibility_registration,
    "local_office": RequirementCategory.eligibility_registration,
    "not_blacklisted": RequirementCategory.eligibility_registration,
    "oem_maf": RequirementCategory.eligibility_registration,
    "land_border": RequirementCategory.eligibility_registration,
    "emd": RequirementCategory.eligibility_registration,
    "manual": RequirementCategory.eligibility_registration,
}


@lru_cache
def analysis_inputs() -> dict[str, Any]:
    """Policy inputs that are not in the tender (labelled estimates, see the JSON note)."""
    return json.loads(_INPUTS.read_text(encoding="utf-8"))


def classify_pq(text: str) -> str:
    """Route a PQ clause to its deterministic check by content (order matters)."""
    t = " ".join(text.lower().split())
    if "consortium" in t and "not be accepted" in t:
        return "single_entity"
    if "registered in india" in t or "in existence" in t:
        return "company_age"
    if "turnover" in t and ("of the turnover in" in t or "infrastructure services" in t or "data centre" in t):
        return "segment_turnover"
    if "turnover" in t:
        return "turnover"
    if "net worth" in t:
        return "net_worth"
    if "similar" in t and "work" in t:
        return "similar_work"
    if "certification" in t or "iso" in t:
        return "certifications"
    if "technically qualified" in t:
        return "tech_staff"
    if "office in" in t:
        return "local_office"
    if "blacklisted" in t or "debarred" in t:
        return "not_blacklisted"
    if "manufacturer" in t or re.search(r"\bmaf\b", t):
        return "oem_maf"
    if "land border" in t:
        return "land_border"
    if "emd" in t or "earnest money" in t:
        return "emd"
    return "manual"


def _criterion_text(block: str) -> str:
    """Drop the trailing 'documentary evidence' column lines (they never end a sentence)."""
    lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
    last = max((i for i, ln in enumerate(lines) if ln.endswith(".")), default=len(lines) - 1)
    return " ".join(lines[: last + 1])


def extract_pq_requirements(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hard-gate requirements: every PQ-xx row plus the single-entity clause."""
    out: list[dict[str, Any]] = []
    for section in sections:
        text = str(section.get("text") or "")
        title = str(section.get("title") or "")
        marks = list(_PQ_MARK.finditer(text))
        if "pre-qualification" in title.lower() and marks:
            for i, mark in enumerate(marks):
                end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
                criterion = _criterion_text(text[mark.end():end])
                out.append(_pq_item(mark.group(1), criterion, section))
        match = _SINGLE_ENTITY.search(text)
        if match and "eligible bidders" in title.lower():
            out.append(_pq_item(match.group(1) or "2.1", " ".join(match.group(2).split()), section))
    return out


def _pq_item(clause_ref: str, text: str, section: dict[str, Any]) -> dict[str, Any]:
    check = classify_pq(text)
    return {
        "clause_ref": clause_ref, "title": f"{clause_ref} pre-qualification", "text": text,
        "category": CHECK_CATEGORY[check].value, "mandatory": True, "hard_gate": True,
        "confidence": 1.0, "check": check, "page": section.get("page_start"),
        "quote": text[:400], "section_id": section.get("section_id"),
        "source": {"doc_id": section.get("doc_id", "unknown"), "page": section.get("page_start"),
                   "section_path": section.get("section_path"), "text_span": text[:400],
                   "tender_version": section.get("tender_version")},
    }


# --------------------------------------------------------------------------- evaluation
class PQContext:
    """Company facts loaded once per run."""

    def __init__(self, session: Session, company_id: str, key_facts: KeyFacts | None,
                 amendment_changes: list[dict[str, Any]] | None = None):
        self.company: CompanyProfile | None = get_company(session, company_id)
        self.financials = get_financials(session, company_id)
        self.certificates = get_certificates(session, company_id)
        self.projects = get_projects(session, company_id)
        self.key_facts = key_facts
        self.extra: dict[str, Any] = dict(self.company.extra) if self.company else {}
        # Corrigendum C1-05 style rule: only the client-certified consortium share counts.
        self.certified_share_only = any(
            c.get("field") == "consortium_experience_value_rule"
            and re.search(r"certified by the client", str(c.get("new_value") or ""), re.IGNORECASE)
            for c in amendment_changes or [])

    @property
    def deadline(self) -> date | None:
        kf = self.key_facts
        return kf.submission_deadline.date() if kf and kf.submission_deadline else None

    def evidence(self, key: str) -> list[SourceSpan]:
        ev = self.extra.get(key)
        if isinstance(ev, dict) and isinstance(ev.get("evidence"), dict):
            ev = ev["evidence"]
        if isinstance(ev, dict) and ev.get("doc_id"):
            return [SourceSpan(doc_id=ev["doc_id"], page=ev.get("page"), text_span=ev.get("span", ""),
                               scope=Scope.kb)]
        return []


def _result(kind: str, status: EligibilityStatus, summary: str, *, calcs: list[Calculation] | None = None,
            evidence: list[SourceSpan] | None = None, actions: list[str] | None = None) -> RuleResult:
    return RuleResult(rule_kind=kind, status=status, summary=summary, calculations=calcs or [],
                      evidence=evidence or [], actions=actions or [])


def _number(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    raw = next(g for g in m.groups() if g)
    return int(raw) if raw.isdigit() else word_to_int(raw)


def evaluate_pq(check: str, text: str, ctx: PQContext) -> RuleResult:
    company = ctx.company
    if company is None:
        return _result(check, EligibilityStatus.needs_human, "Company facts are not loaded.")

    if check == "company_age":
        years = _number(r"at least \w+ \((\d+)\) years|at least (\d+) years", text) or 0
        inc = company.incorporation_date
        if inc is None or ctx.deadline is None:
            return _result(check, EligibilityStatus.needs_human, "Incorporation date or deadline unknown.")
        age = years_between(inc, ctx.deadline)
        ok = age >= years
        return _result(check, EligibilityStatus.meets if ok else EligibilityStatus.gap,
                       f"Incorporated {inc.isoformat()}: {age:.1f} years at the deadline "
                       f"({'>=' if ok else '<'} {years}).", evidence=ctx.evidence("incorporation_evidence"),
                       calcs=[Calculation(label="years in existence", value=round(age, 1))])

    if check == "single_entity":
        ok = not ctx.extra.get("consortium_bid", False)
        return _result(check, EligibilityStatus.meets if ok else EligibilityStatus.gap,
                       "Bidding as a single legal entity." if ok else "Bid is planned as a consortium.")

    if check == "turnover":
        kf = ctx.key_facts
        amounts = parse_all_money(text)
        general = kf.general_turnover_threshold.amount_inr if kf and kf.general_turnover_threshold else (
            amounts[0].amount_inr if amounts else None)
        mse = kf.mse_turnover_threshold.amount_inr if kf and kf.mse_turnover_threshold else (
            amounts[1].amount_inr if len(amounts) > 1 else None)
        if general is None:
            return _result(check, EligibilityStatus.needs_human, "Turnover threshold not found in the clause.")
        turnover_rule = TurnoverRule(general_threshold_inr=general, mse_threshold_inr=mse,
                                     mse_relaxation_allowed=mse is not None, n_years=3, aggregation="average")
        return check_turnover(ctx.financials, turnover_rule, company)

    if check == "segment_turnover":
        amounts = parse_all_money(text)
        if not amounts:
            return _result(check, EligibilityStatus.needs_human, "Segment turnover threshold not found.")
        values = [float(f.extra.get("revenue_infra_services_inr_cr") or "nan") for f in ctx.financials[-3:]]
        if not values or any(v != v for v in values):  # NaN check
            return _result(check, EligibilityStatus.needs_human, "Segment turnover not on record.")
        avg_cr = sum(values) / len(values)
        need_cr = amounts[0].crore
        ok = avg_cr >= need_cr
        return _result(check, EligibilityStatus.meets if ok else EligibilityStatus.gap,
                       f"Average DC/network/managed-services turnover Rs. {avg_cr:.2f} Cr "
                       f"{'>=' if ok else '<'} Rs. {need_cr:.2f} Cr.",
                       calcs=[Calculation(label="average segment turnover (Rs. Cr)", value=round(avg_cr, 2))])

    if check == "net_worth":
        return check_net_worth(ctx.financials, NetWorthRule(min_inr=0, strictly_positive=True, n_years=3))

    if check == "similar_work":
        parsed = parse_requirement(text)
        branches = [SimilarWorkBranch(count=b["count"], min_value_inr=b["min_value_inr"])
                    for b in parsed.get("branches") or []]
        window = re.search(r"between\s+(\d{1,2}-\d{1,2}-\d{4})\s+and\s+(\d{1,2}-\d{1,2}-\d{4})", text)
        reference = parse_date(window.group(2)) if window else ctx.deadline
        similar_rule = SimilarWorkRule(branches=branches,
                                       window_years=(parsed.get("window") or {}).get("years", 7),
                                       reference_date=reference,
                                       required_scope_tags=analysis_inputs()["similar_work_scope_tags"],
                                       count_uncertified_share=not ctx.certified_share_only)
        if not branches:
            return _result(check, EligibilityStatus.needs_human, "Similar-work thresholds not parsed.")
        return check_similar_work(ctx.projects, similar_rule)

    if check == "certifications":
        return _check_certifications(text, ctx)

    if check == "tech_staff":
        need = _number(r"at least (\d+) technically qualified", text) or 0
        have = int(ctx.extra.get("tech_staff_on_payroll") or 0)
        ok = have >= need
        return _result(check, EligibilityStatus.meets if ok else EligibilityStatus.gap,
                       f"{have} technically qualified staff on payroll ({'>=' if ok else '<'} {need}).",
                       evidence=ctx.evidence("tech_staff_evidence"))

    if check == "local_office":
        present = {"local_office"} if ctx.extra.get("office_in_deccan_state") else set()
        undertaking = "undertaking" in text.lower() and bool(ctx.extra.get("local_office_undertaking_policy"))
        res = check_registration(company, present, DocumentPresenceRule(
            document_type="local_office", undertaking_acceptable=undertaking))
        res.evidence = ctx.evidence("office_evidence") + ctx.evidence("local_office_undertaking_policy")
        return res

    if check == "not_blacklisted":
        res = check_registration(company)
        declarations = ctx.extra.get("declarations") or {}
        res.evidence = ctx.evidence("declarations") or [
            SourceSpan(doc_id=(declarations.get("non_blacklisted") or {}).get("evidence", {}).get("doc_id", "KB"),
                       scope=Scope.kb)]
        return res

    if check == "oem_maf":
        held = any(o.get("bid_specific_maf_held") for o in ctx.extra.get("oem_partnerships") or [])
        tender_specific = "bid-specific" in text.lower() or "bid specific" in text.lower()
        return check_registration(company, {"oem_maf"} if held else set(), DocumentPresenceRule(
            document_type="oem_maf", tender_specific=tender_specific))

    if check == "land_border":
        decl = (ctx.extra.get("declarations") or {}).get("land_border_compliant") or {}
        ok = bool(decl.get("value"))
        return _result(check, EligibilityStatus.meets if ok else EligibilityStatus.needs_action,
                       "Land-border declaration on record." if ok else "Land-border declaration missing.",
                       actions=[] if ok else ["Sign the land-border declaration (Format PQ-7)"])

    if check == "emd":
        exempt = company.is_mse and re.search(r"MSE|exemption", text, re.IGNORECASE) is not None
        if exempt:
            return _result(check, EligibilityStatus.meets, "Udyam-registered MSE: EMD exemption applies.",
                           evidence=ctx.evidence("msme"))
        return _result(check, EligibilityStatus.needs_action, "EMD must be furnished.",
                       actions=["Arrange the EMD bank guarantee before submission"])

    return _result("manual", EligibilityStatus.needs_human, "No deterministic check for this clause.")


def _check_certifications(text: str, ctx: PQContext) -> RuleResult:
    """AND of parts; within a part, OR of standards ("CMMI ML3 or above OR ISO/IEC 20000-1")."""
    from backend.app.tools.certificate_rules import check_certification

    parts = [p for p in re.split(r";\s*AND\b|\bAND\s*\(", text, flags=re.IGNORECASE) if find_standards(p)]
    calcs: list[Calculation] = []
    evidence: list[SourceSpan] = []
    statuses: list[EligibilityStatus] = []
    for part in parts:
        options = list(dict.fromkeys(normalize_standard(s) for s in find_standards(part)))
        results = [check_certification(ctx.certificates, CertificationRule(standard=o, display_name=o),
                                       ctx.key_facts) for o in options]
        best = next((r for r in results if r.status.passing), None) or results[0]
        statuses.append(best.status)
        calcs.append(Calculation(label=" OR ".join(options), value=best.summary))
        evidence += best.evidence
    if not parts:
        return _result("certification", EligibilityStatus.needs_human, "No certification standard parsed.")
    if all(s.passing for s in statuses):
        status, summary = EligibilityStatus.meets, "All required certifications are valid on the deadline."
    elif any(s is EligibilityStatus.gap for s in statuses):
        status, summary = EligibilityStatus.gap, "A required certification is missing or not valid on the deadline."
    else:
        status, summary = EligibilityStatus.needs_human, "Certification evidence needs review."
    return RuleResult(rule_kind="certification", status=status, summary=summary, calculations=calcs,
                      evidence=evidence)

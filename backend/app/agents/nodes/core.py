"""Bounded graph nodes for TenderBridge analysis.

Nodes exchange only JSON-compatible values through :class:`TenderState`.  The
deterministic nodes are intentionally usable without an LLM so that eligibility
and scoring remain reproducible and testable.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from backend.app.schemas.assessment import (
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
from backend.app.schemas.requirements import (
    ExtractedRequirement,
    KeyFacts,
    RequirementCategory,
    RequirementExtraction,
)
from backend.app.tools.bid_scoring import factors_from_results
from backend.app.tools.bid_scoring import score_bid as score_bid_policy
from backend.app.tools.certificate_rules import check_certification
from backend.app.tools.facts import (
    get_certificates,
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


# Clause markers: obligations, definitions, buyer rights and limits all bind the bidder.
_MARKERS = re.compile(r"\b(shall|must|required|mandatory|eligible|minimum|at least|not less than|"
                      r"not exceed|valid|submit|means|may|liable|prevail)\b", re.I)
_BINDING = re.compile(r"\b(shall|must|required|mandatory|means|not exceed|prevail)\b", re.I)
_OPTIONAL = re.compile(r"\b(preferred|optional|desirable|additional marks)\b", re.I)
_AMENDED_COLUMN = re.compile(r"\b(amended|revised|response|clarification)\b", re.I)
# A wrapped PDF line starts a new block only when it opens a list item or a numbered clause.
_BLOCK_START = re.compile(r"^(\(?[a-z0-9]{1,3}\)|[a-z0-9]{1,3}\)|[•▪\-–]\s|\d+(\.\d+)+[A-Z]?\s)", re.I)
_ABBREVIATIONS = {"rs", "no", "nos", "sl", "cl", "e.g", "i.e", "etc", "viz", "vs", "dr", "mr", "ms",
                  "approx", "fig", "para", "ltd", "pvt", "co", "inc", "st", "max", "min"}
_SERIAL = re.compile(r"^[A-Z]{0,2}\d{1,3}[a-z]?\.?$")
_CATEGORY_TOKENS = (
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
)


def _category(text: str) -> RequirementCategory:
    lower = text.lower()
    return next((c for token, c in _CATEGORY_TOKENS if token in lower), RequirementCategory.other)


def _sentences(text: str, table_cells: list[str] | None = None) -> list[str]:
    """Rejoin wrapped PDF lines, then split on real sentence ends (not "Rs." or "No.").

    Lines that are part of a structured table cell are treated as breaks: the table
    rows are extracted separately, and cell text has no full stops to end a sentence.
    """
    cells = [" ".join(c.lower().split()) for c in table_cells or [] if c]
    blocks: list[list[str]] = []
    for line in (ln.strip() for ln in text.splitlines()):
        flat = " ".join(line.lower().split())
        if not line or (cells and any(flat in cell for cell in cells)):
            blocks.append([])
        elif not blocks or not blocks[-1] or _BLOCK_START.match(line):
            blocks.append([line])
        else:
            blocks[-1].append(line)
    sentences: list[str] = []
    for block in filter(None, blocks):
        current: list[str] = []
        for word in " ".join(block).split():
            current.append(word)
            stem = word.rstrip(".").lower()
            if (word.endswith((".", "?")) and stem not in _ABBREVIATIONS
                    and not re.fullmatch(r"[a-z]|\d+(\.\d+)*", stem, re.I)):
                sentences.append(" ".join(current))
                current = []
        if current:
            sentences.append(" ".join(current))
    return sentences


def _table_requirements(section: dict[str, Any]) -> list[ExtractedRequirement]:
    """One candidate per table row; optional columns and amendment columns are kept apart."""
    out: list[ExtractedRequirement] = []
    for t_index, table in enumerate(section.get("tables") or [], 1):
        headers = [str(h or "") for h in table.get("headers") or []]
        amended = next((i for i, h in enumerate(headers) if _AMENDED_COLUMN.search(h)), None)
        optional = {i for i, h in enumerate(headers) if _OPTIONAL.search(h)}
        for r_index, row in enumerate(table.get("rows") or [], 1):
            cells = [" ".join(str(c or "").split()) for c in row]
            ref = f"{section.get('section_id', 'section')}-T{t_index}R{r_index}"
            if amended is not None:
                candidates = [(cells[amended], True)] if amended < len(cells) else []
            else:
                main = [c for i, c in enumerate(cells) if c and i not in optional and not _SERIAL.match(c)]
                candidates = [("; ".join(main), True)] if len(main) >= 2 else []
                candidates += [(cells[i], False) for i in sorted(optional) if i < len(cells) and cells[i]]
            for text, mandatory in candidates:
                if len(text.split()) < (3 if mandatory else 2):  # "Valid CCIE" is a real preference
                    continue
                out.append(ExtractedRequirement(
                    clause_ref=ref, title=str(section.get("title", "")), text=text,
                    category=_category(text), mandatory=mandatory,
                    page=table.get("page") or section.get("page_start"), quote=text[:400],
                    confidence=0.6))
    return out


def _heuristic_shred(section: dict[str, Any]) -> RequirementExtraction:
    from backend.app.schemas.requirements import RequirementExtraction
    extracted: list[ExtractedRequirement] = []
    cells = [str(c) for t in section.get("tables") or []
             for row in [t.get("headers") or [], *(t.get("rows") or [])] for c in row]
    for index, sentence in enumerate(_sentences(str(section.get("text", "")), cells)):
        if not _MARKERS.search(sentence):
            continue
        extracted.append(ExtractedRequirement(
            clause_ref=str(section.get("clause_ref") or f"{section.get('section_id', 'section')}-{index + 1}"),
            title=str(section.get("title", "")), text=sentence, category=_category(sentence),
            mandatory=bool(_BINDING.search(sentence)) and not _OPTIONAL.search(sentence),
            page=section.get("page_start"), quote=sentence[:400], confidence=0.65,
        ))
    return RequirementExtraction(requirements=extracted)


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


class _SectionRequirements(BaseModel):
    section: int = Field(description="The [S<n>] number of the section")
    requirements: list[ExtractedRequirement] = Field(default_factory=list)


class _BatchExtraction(BaseModel):
    sections: list[_SectionRequirements] = Field(default_factory=list)


def _batches(sections: list[dict[str, Any]], max_tokens: int, max_sections: int = 30) -> list[list[dict[str, Any]]]:
    """Consecutive sections grouped up to ~max_tokens of text (a large section goes alone)."""
    out: list[list[dict[str, Any]]] = []
    size = 0
    for sec in sections:
        tokens = len(str(sec.get("text", ""))) // 4 + 20
        if out and size + tokens <= max_tokens and len(out[-1]) < max_sections:
            out[-1].append(sec)
            size += tokens
        else:
            out.append([sec])
            size = tokens
    return out


def shred_batch_tokens(model: str) -> int:
    """Fewer, larger batches where the per-minute token limit allows (few requests/day on free tiers);
    a batch plus its answer must stay under the model's tokens/minute (e.g. Groq 8K)."""
    from backend.app.core.config import get_settings
    from backend.app.llm.ratelimit import limits_for

    tpm = limits_for(model).tpm
    cap = get_settings().shred_batch_tokens
    return min(cap, tpm // 3) if tpm else cap


def _extract_sections(sections: list[dict[str, Any]]) -> list[tuple[dict[str, Any], list[ExtractedRequirement], bool]]:
    """(section, requirements, heuristic_used) per section.

    With a configured model (and SHRED_WITH_LLM), sections go in batches (shred_batch_tokens): about
    4 calls for TDR-001 on Gemini instead of ~100, which fits free-tier per-day and per-minute limits. A section the
    model leaves out, or a failed call, falls back to the deterministic extractor for that section.
    """
    from backend.app.core.config import get_settings
    from backend.app.guardrails.injection import wrap_untrusted
    from backend.app.llm.factory import is_fake, load_prompt, resolve, structured_call

    settings = get_settings()
    model = resolve("shred_requirements").model
    if not settings.shred_with_llm or is_fake(model):
        return [(sec, _heuristic_shred(sec).requirements, True) for sec in sections]
    out = []
    for batch in _batches(sections, shred_batch_tokens(model)):
        user = "\n\n".join(
            wrap_untrusted(str(sec.get("text", "")),
                           f"[S{i}] {sec.get('section_path') or sec.get('title') or ''} (page {sec.get('page_start')})")
            for i, sec in enumerate(batch, 1))
        result = structured_call(
            "shred_requirements", _BatchExtraction, system=load_prompt("shred_requirements"), user=user,
            heuristic=lambda b=batch: _BatchExtraction(sections=[
                _SectionRequirements(section=i, requirements=_heuristic_shred(sec).requirements)
                for i, sec in enumerate(b, 1)]))
        by_index = {entry.section: entry.requirements for entry in result.value.sections}
        for i, sec in enumerate(batch, 1):
            if i in by_index and not result.fallback:
                out.append((sec, by_index[i], False))
            else:
                out.append((sec, _heuristic_shred(sec).requirements, True))
    return out


def shred_requirements(state: TenderState) -> dict[str, Any]:
    """Requirement candidates: the PQ table deterministically (hard gates), every other section by
    the model in batches or by the deterministic extractor, plus structured table rows."""
    from backend.app.agents.prequalification import extract_pq_requirements

    # Pre-qualification rows are the hard gates; they get a deterministic extractor.
    pq = extract_pq_requirements(state.get("sections", []))
    pq_sections = {r["section_id"] for r in pq if r["clause_ref"].startswith("PQ-")}
    extracted: list[dict[str, Any]] = [{
        **r, "section_path": r["source"]["section_path"], "llm_fallback": False,
        "tender_id": state["tender_id"], "tender_version": state["tender_version"],
    } for r in pq]
    todo = [sec for sec in state.get("sections", [])
            if str(sec.get("text", "")).strip() and sec.get("section_id") not in pq_sections]
    for section, items, heuristic_used in _extract_sections(todo):
        for item, from_heuristic in [(i, heuristic_used) for i in items] + [
                (row, False) for row in _table_requirements(section)]:
            sentence = item.text
            extracted.append({
                **item.model_dump(mode="json"),
                "source": {**_source(section, sentence), "page": item.page or section.get("page_start")},
                "llm_fallback": from_heuristic,
                "section_path": section.get("section_path"),
                "hard_gate": False,  # hard gates come only from the PQ table above
                "tender_id": state["tender_id"],
                "tender_version": state["tender_version"],
            })
    return {"raw_requirements": extracted}


def merge_and_dedupe(state: TenderState) -> dict[str, Any]:
    requirements: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], str] = {}
    used_ids: set[str] = set()
    for index, raw in enumerate(state.get("raw_requirements", [])):
        text = str(raw.get("text", "")).strip()
        key = (str(raw.get("clause_ref") or ""), re.sub(r"\W+", " ", text.lower()).strip())
        if key in seen:
            continue
        requirement_id = f"REQ-{raw.get('clause_ref') or index + 1}"
        if requirement_id in used_ids:
            requirement_id = f"{requirement_id}-{index + 1}"
        used_ids.add(requirement_id)
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
            "check": raw.get("check"),
        })
    return {"requirements": requirements}


_KEY_FACT_HINTS = re.compile(r"\b(last date|submission|opening|pre-?bid|emd|earnest money|performance (bank )?"
                             r"guarantee|pbg|payment|penalt|liquidated|validity|estimated cost|evaluation|qcbs)\b",
                             re.I)


def _key_fact_context(sections: list[dict[str, Any]], max_tokens: int = 6000) -> str:
    """Only sections that can hold key facts (fact sheet, dates, EMD/PBG, payment, penalties), so the
    model gap-filler stays within one free-tier minute of tokens instead of sending the whole tender."""
    from backend.app.guardrails.injection import wrap_untrusted

    picked, size = [], 0
    for sec in sorted(sections, key=lambda x: -len(_KEY_FACT_HINTS.findall(str(x.get("text", ""))))):
        text = str(sec.get("text", ""))
        if not _KEY_FACT_HINTS.search(text) or size + len(text) // 4 > max_tokens:
            continue
        picked.append(wrap_untrusted(text, f"{sec.get('section_path') or ''} (page {sec.get('page_start')})"))
        size += len(text) // 4
    return "\n\n".join(picked)


def extract_key_facts(state: TenderState) -> dict[str, Any]:
    """Deterministic, sourced extraction first; the LLM (when configured) only fills gaps."""
    from backend.app.agents.key_facts import extract_key_facts_deterministic, merge_key_facts

    sections = state.get("sections", [])
    found = extract_key_facts_deterministic(state["tender_id"], state["tender_version"], sections)
    if state.get("key_facts"):
        validated = merge_key_facts(KeyFacts.model_validate(state["key_facts"]), found)
    elif not found.missing:
        validated = found
    else:
        from backend.app.llm.factory import load_prompt, structured_call
        text = _key_fact_context(sections)
        result = structured_call("extract_key_facts", KeyFacts, system=load_prompt("extract_key_facts"),
                                 user=text, heuristic=lambda: found)
        model_facts = result.value.model_copy(update={
            "tender_id": state["tender_id"], "tender_version": state["tender_version"]})
        validated = merge_key_facts(model_facts, found)
    return {"key_facts": dump(validated)}


def route_requirements(state: TenderState) -> dict[str, Any]:
    """Decide how each requirement is checked: a PQ rule, a Phase 2 tool, or RAG/human review."""
    from backend.app.agents.subgraphs.requirement_router import route_requirement

    routes = []
    for item in state.get("requirements", []):
        if item.get("check"):
            routes.append({"requirement_id": item["requirement_id"], "category": item.get("category"),
                           "tool": f"pq:{item['check']}"})
        else:
            routes.append(route_requirement(item))
    return {"routes": routes}


def eligibility_and_risk(state: TenderState) -> dict[str, Any]:
    """Run each routed check against SQL facts, then build the commercial risk register.

    Hard gates (PQ) are evaluated deterministically. Other requirements are
    either checked by a parsed rule or left `needs_human` for the bid team;
    they are not risks. Risks come only from contract clauses compared with
    the company's approved positions.
    """
    from backend.app.agents.commercial_terms import detect_commercial_risks
    from backend.app.agents.prequalification import PQContext, evaluate_pq
    from backend.app.db.engine import session_scope
    from backend.app.tools.facts import get_risk_positions

    company_id = state.get("company_id")
    key_facts = KeyFacts.model_validate(state["key_facts"]) if state.get("key_facts") else None
    compliance: list[dict[str, Any]] = []
    # Impact mode: a hard-gate check no amendment touches keeps its base-version result.
    reusable = set(state.get("reusable_checks") or []) if state.get("mode") == "impact" else set()
    previous = {c["requirement_id"]: c for c in state.get("previous_compliance") or []}
    with session_scope() as session:
        ctx = PQContext(session, company_id, key_facts, state.get("amendment_changes")) if company_id else None
        financials = get_financials(session, company_id) if company_id else []
        certificates = get_certificates(session, company_id) if company_id else []
        positions = get_risk_positions(session, company_id) if company_id else []
        evidence_index = _evidence_index(session, company_id) if company_id else None
        for req in state.get("requirements", []):
            prior = previous.get(req["requirement_id"])
            if req.get("check") in reusable and prior is not None:
                compliance.append({**prior, "tender_version": state["tender_version"],
                                   "reused_from_version": prior.get("reused_from_version")
                                   or prior.get("tender_version")})
                continue
            result = None
            if req.get("check") and ctx is not None:
                result = evaluate_pq(req["check"], req.get("text", ""), ctx)
            elif req.get("parsed_rule") and ctx is not None:
                try:
                    from pydantic import TypeAdapter
                    parsed = TypeAdapter(EligibilityRule).validate_python(req["parsed_rule"])
                    if parsed.kind == "turnover":
                        result = check_turnover(financials, parsed, ctx.company)
                    elif parsed.kind == "net_worth":
                        result = check_net_worth(financials, parsed)
                    elif parsed.kind == "certification":
                        result = check_certification(certificates, parsed, key_facts)
                except (TypeError, ValueError):
                    result = None
            status = result.status if result else EligibilityStatus.needs_human
            summary = result.summary if result else "Not machine-checkable: assign an owner to confirm."
            evidence = result.evidence if result else []
            if result is None and company_id and req.get("mandatory", True) and evidence_index is not None:
                evidence = _candidate_evidence(session, company_id, req, evidence_index)
                if evidence:
                    summary = ("Not machine-checkable: candidate company evidence attached for the "
                               "owner to confirm.")
            compliance.append(ComplianceItem(
                requirement_id=req["requirement_id"], tender_id=state["tender_id"],
                tender_version=state["tender_version"], category=req.get("category", "other"),
                mandatory=req.get("mandatory", True), hard_gate=req.get("hard_gate", False),
                status=status, summary=summary, rule_result=result,
                tender_source=req["source"], company_evidence=evidence,
                actions=result.actions if result else [],
                confidence=req.get("confidence", 0.65), checked_by="rule" if result else "human",
            ).model_dump(mode="json"))
        risks = detect_commercial_risks(state.get("sections", []), key_facts, positions,
                                        tender_id=state["tender_id"], version=state["tender_version"])
    return {"compliance": compliance, "risks": risks}


# Requirements no rule can check get candidate evidence from the company KB (RAG finds evidence,
# a person decides). Searched as the least-privileged role, so restricted documents are never
# attached to a compliance item that analysts can open.
EVIDENCE_ROLE = "analyst"
EVIDENCE_K = 3


def _evidence_index(session: Any, company_id: str) -> Any:
    from backend.app.retrieval.filters import SearchFilters
    from backend.app.retrieval.keyword import prepare_candidates
    from backend.app.schemas.documents import Scope

    try:
        index = prepare_candidates(session, SearchFilters(scope=Scope.kb, company_id=company_id,
                                                          role=EVIDENCE_ROLE))
    except Exception:  # an empty or unreachable KB leaves items for humans, as before
        return None
    return index if index.rows else None


def _candidate_evidence(session: Any, company_id: str, req: dict[str, Any], index: Any) -> list[Any]:
    from backend.app.tools.company_search import search_company_kb

    hits = search_company_kb(session, company_id, str(req.get("text", ""))[:500], k=EVIDENCE_K,
                             role=EVIDENCE_ROLE, candidates=index)
    return [h.to_span() for h in hits]


def _static_scores() -> dict[str, float]:
    from backend.app.agents.prequalification import analysis_inputs
    return {k: float(v) for k, v in analysis_inputs()["static_scores"].items()}


def bid_score(state: TenderState) -> dict[str, Any]:
    compliance = [ComplianceItem.model_validate(i) for i in state.get("compliance", [])]
    hard_items = [i for i in compliance if i.hard_gate]
    # Policy: only a hard-gate `gap` forces NO_BID. A hard gate that needs an
    # action or a human (e.g. bid-specific OEM MAF) passes with a condition, so
    # the recommendation can be at most BID_WITH_CONDITIONS.
    hard = [
        HardGateResult(requirement_id=i.requirement_id, label=i.requirement_id,
                       status=i.status.value, passed=i.status is not EligibilityStatus.gap,
                       summary=i.summary, evidence=i.company_evidence)
        for i in hard_items
    ]
    risk_items = [RiskItem.model_validate(i) for i in state.get("risks", [])]
    policy = state.get("scoring_policy") or {}
    factors = state.get("scoring_factors") or factors_from_results(
        [item.status for item in hard_items],  # eligibility confidence is over hard gates only
        [item.level for item in risk_items],
        static_scores=state.get("static_scores") or _static_scores(),
        policy=policy or None,
    )
    # Conditions: hard gates that pass only with an action, undertaking or human check.
    conditions = [f"{i.requirement_id}: {i.summary}" for i in hard_items
                  if i.status in (EligibilityStatus.needs_action, EligibilityStatus.partial,
                                  EligibilityStatus.meets_with_undertaking,
                                  EligibilityStatus.needs_human)]
    # Deal-breaker clauses that need an approver (e.g. CEO for uncapped liability).
    conditions += [f"Approval needed: {i.summary}" for i in risk_items
                   if i.level is RiskLevel.escalate]
    assessment = score_bid_policy(
        tender_id=state["tender_id"],
        tender_version=state["tender_version"],
        analysis_run_id=state["analysis_run_id"],
        factors=factors,
        hard_gates=hard,
        conditions=conditions,
        top_risks=[i.summary for i in risk_items[:5]],
        analysis_mode=state.get("analysis_mode", "focused"),
        rule_pack=policy or None,
    )
    from backend.app.guardrails.policy_enforcer import enforce_assessment
    dumped = assessment.model_dump(mode="json")
    enforce_assessment(dumped)  # a failed hard gate can never leave scoring as a bid
    return {"assessment": dumped}


def gate1_review(state: TenderState) -> dict[str, Any]:
    """Pause after deterministic scoring until an approver makes Gate 1 explicit."""
    if state.get("gate1_decision"):
        return {}
    assessment = state.get("assessment") or {}
    try:
        from langgraph.types import interrupt
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("LangGraph is required for Gate 1") from exc
    decision = interrupt({
        "gate": "gate1", "tender_id": state["tender_id"],
        "tender_version": state["tender_version"], "assessment": assessment,
        "message": "Approve, reject, or defer the bid/no-bid recommendation.",
    })
    return {"gate1_decision": decision}


def write_no_bid_report(state: TenderState) -> dict[str, Any]:
    assessment = state.get("assessment") or {}
    return {"no_bid_report": {
        "tender_id": state.get("tender_id"), "version": state.get("tender_version"),
        "recommendation": assessment.get("recommendation", Recommendation.NO_BID.value),
        "score": assessment.get("score", 0), "hard_gate_failures": assessment.get("hard_gate_failures", []),
        "reasons": assessment.get("top_risks", []),
    }}


def reconcile_corrigenda(state: TenderState) -> dict[str, Any]:
    """Apply confirmed amendments: amended key facts (with corrigendum sources) and the
    set of checks they invalidate. Nothing is applied that a reviewer did not confirm."""
    from backend.app.agents.prequalification import CHECK_CATEGORY
    from backend.app.schemas.amendments import AmendmentChange
    from backend.app.tools.amendment_diff import apply_changes_to_key_facts

    raw = state.get("amendment_changes") or []
    if not raw:
        return {"invalidated_checks": [], "reusable_checks": []}
    changes = [AmendmentChange.model_validate(c) for c in raw]
    update: dict[str, Any] = {}
    if state.get("key_facts"):
        kf = apply_changes_to_key_facts(KeyFacts.model_validate(state["key_facts"]), changes)
        update["key_facts"] = dump(kf)
    invalidated = sorted({k for c in changes if c.kind != "no_change" for k in c.downstream_impacts})
    change_map: dict[str, list[str]] = {}
    for c in changes:
        for key in c.downstream_impacts:
            change_map.setdefault(key, []).append(c.change_id)
    update.update({
        "invalidated_checks": invalidated,
        "reusable_checks": sorted(set(CHECK_CATEGORY) - set(invalidated) - {"manual"}),
        "change_map": change_map,
    })
    return update


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

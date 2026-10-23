"""Model usage, guardrail events and per-run metric aggregation."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.schemas.documents import GuardrailFlag

log = get_logger(__name__)


def record_model_usage(run_id: str | None, node: str | None, model: str, tier: str,
                       input_tokens: int, output_tokens: int, cost_usd: float, latency_ms: float,
                       ok: bool, error: str | None = None, cached: bool = False) -> None:
    from backend.app.db.engine import session_scope
    from backend.app.db.models import ModelUsage
    try:
        with session_scope() as s:
            s.add(ModelUsage(run_id=run_id, node=node, model=model, tier=tier,
                             input_tokens=input_tokens, output_tokens=output_tokens,
                             cost_usd=cost_usd, latency_ms=latency_ms, ok=ok,
                             error=(error or None) and error[:2000], cached=cached))
    except Exception as exc:
        log.warning("model usage write failed: %s", exc)


def record_guardrail(flag: GuardrailFlag, *, tender_id: str | None = None,
                     run_id: str | None = None, session: Session | None = None) -> None:
    """Persist a guardrail event. Pass `session` when called inside an open
    transaction (avoids a second writer, which SQLite would block)."""
    from backend.app.db.engine import session_scope
    from backend.app.db.models import GuardrailEvent
    from backend.app.ops.langsmith import redact_text

    row = GuardrailEvent(tender_id=tender_id, run_id=run_id, kind=flag.kind,
                         severity=flag.severity, doc_id=flag.doc_id, page=flag.page,
                         excerpt=redact_text(flag.excerpt or "")[:2000],
                         detail=flag.detail, quarantined=flag.quarantined)
    try:
        if session is not None:
            session.add(row)
            return
        with session_scope() as s:
            s.add(row)
    except Exception as exc:
        log.warning("guardrail event write failed: %s", exc)


def guardrail_to_dict(r) -> dict[str, Any]:
    return {"id": r.id, "ts": r.ts.isoformat() if r.ts else None, "tender_id": r.tender_id,
            "run_id": r.run_id, "kind": r.kind, "severity": r.severity, "doc_id": r.doc_id,
            "page": r.page, "excerpt": r.excerpt, "detail": r.detail,
            "quarantined": r.quarantined, "resolved": r.resolved}


def latest_eval_results() -> dict[str, Any] | None:
    results_dir = get_settings().project_root / "evals" / "results"
    if not results_dir.exists():
        return None
    files = sorted(results_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return {"file": f.name, "measured": True, "results": data}
        except Exception:
            continue
    return None


def run_metrics(session: Session, run_id: str | None) -> dict[str, Any]:
    from backend.app.db.models import AnalysisRun, GuardrailEvent, ModelUsage, RunEvent

    out: dict[str, Any] = {"run_id": run_id}
    q = select(ModelUsage)
    if run_id:
        q = q.where(ModelUsage.run_id == run_id)
    usage = session.scalars(q).all()
    per_node: dict[str, dict[str, Any]] = defaultdict(lambda: {"calls": 0, "input_tokens": 0,
                                                               "output_tokens": 0, "cost_usd": 0.0,
                                                               "latency_ms": 0.0, "errors": 0})
    for u in usage:
        n = per_node[u.node or "unknown"]
        n["calls"] += 1
        n["input_tokens"] += u.input_tokens
        n["output_tokens"] += u.output_tokens
        n["cost_usd"] += u.cost_usd
        n["latency_ms"] += u.latency_ms
        n["errors"] += 0 if u.ok else 1
    out["llm"] = {
        "calls": len(usage),
        "input_tokens": sum(u.input_tokens for u in usage),
        "output_tokens": sum(u.output_tokens for u in usage),
        "cost_usd": round(sum(u.cost_usd for u in usage), 6),
        "models": sorted({u.model for u in usage}),
        "per_node": dict(per_node),
    }

    # Node latency from node_started/node_completed events
    latency: dict[str, float] = {}
    if run_id:
        evs = session.scalars(select(RunEvent).where(RunEvent.run_id == run_id)
                              .order_by(RunEvent.id)).all()
        started: dict[str, Any] = {}
        for e in evs:
            if e.event == "node_started" and e.node:
                started[e.node] = e.created_at
            elif e.event in ("node_completed", "node_failed") and e.node in started:
                latency[e.node] = latency.get(e.node, 0.0) + \
                    (e.created_at - started.pop(e.node)).total_seconds() * 1000
    out["latency_ms_by_node"] = latency

    gq = select(GuardrailEvent)
    run = session.get(AnalysisRun, run_id) if run_id else None
    if run is not None:
        gq = gq.where((GuardrailEvent.run_id == run_id) | (GuardrailEvent.tender_id == run.tender_id))
    out["guardrail_events"] = [guardrail_to_dict(g) for g in
                               session.scalars(gq.order_by(GuardrailEvent.id.desc()).limit(200)).all()]
    out["node_timings"] = (run.usage or {}).get("node_timings", {}) if run else {}
    if run is not None:
        out["run"] = {"status": run.status, "replay": run.replay, "mode": run.mode,
                      "analysis_mode": run.analysis_mode,
                      "started_at": run.started_at.isoformat() if run.started_at else None,
                      "finished_at": run.finished_at.isoformat() if run.finished_at else None}
    out["eval_results"] = latest_eval_results()
    return out

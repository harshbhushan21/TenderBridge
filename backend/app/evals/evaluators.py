"""Evaluators for the Phase 8 harness. They implement the matching rules written in the gold files.

Requirements (requirements_gold.json `metrics.matching_rule`): an extracted requirement matches a
gold item if it is on the same page (+/-1) of the same file and token-level F1 with the gold text
is >= 0.6, or it contains the gold `locate_span` (case-insensitive, whitespace-normalised).
Retrieval (retrieval_qa.json `metrics`): recall@k and MRR, a hit being the same file and page.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

F1_THRESHOLD = 0.6


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def token_f1(gold: str, predicted: str) -> float:
    g, p = Counter(re.findall(r"[a-z0-9]+", _norm(gold))), Counter(re.findall(r"[a-z0-9]+", _norm(predicted)))
    common = sum((g & p).values())
    if not common:
        return 0.0
    precision, recall = common / sum(p.values()), common / sum(g.values())
    return 2 * precision * recall / (precision + recall)


def basename(path: str | None) -> str:
    return PurePosixPath(path or "").name


def requirement_matches(gold: dict[str, Any], row: dict[str, Any], filename: str | None) -> bool:
    if _norm(gold.get("locate_span")) and _norm(gold.get("locate_span")) in _norm(row.get("text")):
        return True
    page = (row.get("source") or {}).get("page")
    return (page is not None and gold.get("page") is not None and abs(int(page) - int(gold["page"])) <= 1
            and filename == basename(gold.get("source_file"))
            and token_f1(str(gold.get("text", "")), str(row.get("text", ""))) >= F1_THRESHOLD)


def evaluate_requirements(gold: list[dict[str, Any]], rows: list[dict[str, Any]],
                          files: dict[str, str], *, version: int, live_only: bool) -> dict[str, Any]:
    """Recall over gold items effective in `version`; `files` maps tender doc_id -> filename."""
    in_version = [g for g in gold if f"v{version}" in (g.get("effective_in") or [])]
    scope = [g for g in in_version if g.get("live_subset")] if live_only else in_version

    def file_of(row: dict[str, Any]) -> str | None:
        return files.get(str((row.get("source") or {}).get("doc_id")))

    matched = [(g, next((r for r in rows if requirement_matches(g, r, file_of(r))), None)) for g in scope]
    mandatory = [(g, r) for g, r in matched if g.get("mandatory")]
    hits = [(g, r) for g, r in matched if r is not None]
    relevant = [r for r in rows if any(requirement_matches(g, r, file_of(r)) for g in in_version)]
    return {
        "version": version, "scope": "live_subset" if live_only else "all_gold",
        "mandatory_expected": len(mandatory),
        "mandatory_found": sum(r is not None for _, r in mandatory),
        "mandatory_recall": round(sum(r is not None for _, r in mandatory) / len(mandatory), 4) if mandatory else 0.0,
        "recall_all": round(len(hits) / len(scope), 4) if scope else 0.0,
        "precision": round(len(relevant) / len(rows), 4) if rows else 0.0,
        "mandatory_flag_accuracy": round(sum(bool(g.get("mandatory")) == bool(r.get("mandatory"))
                                             for g, r in hits) / len(hits), 4) if hits else 0.0,
        "extracted": len(rows),
        "missed": [g["requirement_id"] for g, r in matched if r is None],
    }


def evaluate_retrieval(questions: list[dict[str, Any]], retrieved: dict[str, list[tuple[str, int | None]]],
                       k: int = 6) -> dict[str, Any]:
    """`retrieved` maps qa_id -> ranked (filename, page) pairs; a hit is the same file and page."""
    hits, reciprocal, misses = 0, 0.0, []
    for q in questions:
        wanted = {(basename(r.get("file")), r.get("page")) for r in q.get("relevant") or []}
        ranked = retrieved.get(q["qa_id"], [])[:k]
        rank = next((i for i, hit in enumerate(ranked, 1) if hit in wanted), None)
        if rank:
            hits += 1
            reciprocal += 1 / rank
        else:
            misses.append(q["qa_id"])
    n = len(questions)
    return {"questions": n, f"recall_at_{k}": round(hits / n, 4) if n else 0.0,
            "mrr": round(reciprocal / n, 4) if n else 0.0, "missed": misses}


def evaluate_claims(expected: dict[str, list[str]], verdicts: dict[str, str]) -> dict[str, Any]:
    """Compare verifier verdicts with the fixture's expected outcome per claim."""
    want = {**{c: "struck" for c in expected.get("remove_or_rewrite", [])},
            **{c: "kept" for c in expected.get("keep_with_citation", [])},
            **{c: "conditional" for c in expected.get("keep_with_condition", [])}}
    got = {c: ("struck" if v in {"unsupported", "contradicted"} else "conditional" if v == "conditional"
               else "kept") for c, v in verdicts.items()}
    bad = [c for c, w in want.items() if w == "struck"]
    good = [c for c, w in want.items() if w != "struck"]
    return {
        "claims": len(want),
        "bad_claims_struck": f"{sum(got.get(c) == 'struck' for c in bad)}/{len(bad)}",
        "good_claims_wrongly_struck": [c for c in good if got.get(c) == "struck"],
        "agreement": round(sum(got.get(c) == w for c, w in want.items()) / len(want), 4) if want else 0.0,
        "disagreements": {c: {"expected": w, "got": got.get(c)} for c, w in want.items() if got.get(c) != w},
    }

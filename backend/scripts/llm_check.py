"""Check the configured models before a demo: routing, keys, limits, and the expected load.

Usage: uv run python dev.py llm-check [--ping]

Without --ping nothing is sent anywhere. With --ping, each configured (non-fake) model gets one
tiny request, to catch a wrong model id or key before the demo (it uses a little quota).
"""
from __future__ import annotations

import argparse
import json
import math
import time

from pydantic import BaseModel

from backend.app.core.config import get_settings, provider_configured
from backend.app.llm.factory import is_fake, resolve
from backend.app.llm.ratelimit import limits_for

# Nodes that can call a model, and how often for one tender (TDR-001 analysis + one drafted section).
NODES = ("shred_requirements", "extract_key_facts", "write_sections", "rewrite_failed")
OUTPUT_TOKENS = {"shred_requirements": 1800, "extract_key_facts": 800, "write_sections": 900, "rewrite_failed": 500}


class Pong(BaseModel):
    ok: bool


def _extraction_load(batch_tokens: int) -> tuple[int, int]:
    """Calls and input tokens for TDR-001's non-PQ sections in batches (from the checked-in extraction)."""
    from backend.app.agents.nodes.core import _batches

    data = json.loads((get_settings().demo_data_dir / "tender/TDR-001/extracted/tender_sections.json")
                      .read_text(encoding="utf-8"))
    sections = [s for d in data["documents"] for s in d.get("sections") or [] if str(s.get("text", "")).strip()]
    batches = _batches(sections, batch_tokens)
    return len(batches), sum(len(str(s["text"])) // 4 for s in sections) + 300 * len(batches)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ping", action="store_true", help="send one tiny request to each configured model")
    args = parser.parse_args()
    s = get_settings()

    print("TenderBridge model check\n")
    calls_tokens = {"shred_requirements": _extraction_load(s.shred_batch_tokens) if s.shred_with_llm else (0, 0),
                    "extract_key_facts": (0, 0),  # TDR-001's key facts are all found deterministically
                    "write_sections": (1, 4500), "rewrite_failed": (1, 1500)}
    per_model: dict[str, list[tuple[int, int]]] = {}
    print(f"{'node':<20} {'model':<40} {'key':<5} {'calls':>5} {'tokens':>8}")
    for node in NODES:
        route = resolve(node)
        provider = route.model.split(":", 1)[0]
        calls, tokens = calls_tokens[node]
        if is_fake(route.model):
            print(f"{node:<20} {route.model:<40} {'-':<5} {'offline (deterministic fallback)':>14}")
            continue
        total = tokens + calls * OUTPUT_TOKENS[node]
        per_model.setdefault(route.model, []).append((calls, total))
        print(f"{node:<20} {route.model:<40} {'yes' if provider_configured(provider) else 'NO':<5} "
              f"{calls:>5} {total:>8}")
    if not s.shred_with_llm:
        print("\nSHRED_WITH_LLM=false: requirement extraction is deterministic (no model calls).")

    if per_model:
        print("\nPer model, for one tender (v1 analysis + one drafted section):")
        for model, loads in per_model.items():
            calls = sum(c for c, _ in loads)
            tokens = sum(t for _, t in loads)
            lim = limits_for(model)
            minutes = max(calls / lim.rpm if lim.rpm else 0, tokens / lim.tpm if lim.tpm else 0)
            limit_txt = f"{lim.rpm or '∞'} rpm / {lim.tpm or '∞'} tpm"
            print(f"  {model:<40} {calls:>3} calls, ~{tokens:>6} tokens · limits {limit_txt} · "
                  f"at least {math.ceil(minutes * 60) if minutes else 0}s of quota time")
        print("  A v2 re-analysis after the corrigendum reuses cached answers for unchanged sections.")

    print(f"\nEmbeddings: {s.embedding_provider} ({s.embedding_dim}-d) · LLM cache: {'on' if s.llm_cache else 'off'}")
    print(f"LangSmith tracing: {'on' if s.langsmith_tracing and (s.langsmith_api_key or s.langchain_api_key) else 'off'}"
          f" (project {s.langsmith_project})")

    if args.ping:
        from backend.app.llm.factory import _build_chat_model, _messages
        print("\nPing (one tiny request per model):")
        for model in sorted({resolve(n).model for n in NODES if not is_fake(resolve(n).model)}):
            t0 = time.perf_counter()
            try:
                llm = _build_chat_model(model, 0.0, 64, 30.0)
                try:
                    out = llm.with_structured_output(Pong).invoke(_messages("Reply ok=true.", "ping"))
                    ok = bool(getattr(out, "ok", False))
                except NotImplementedError:
                    ok = bool(llm.invoke(_messages("Reply with the word ok.", "ping")).content)
                print(f"  {model:<40} {'ok' if ok else 'answered, unexpected output'} "
                      f"({(time.perf_counter() - t0) * 1000:.0f} ms)")
            except Exception as exc:
                print(f"  {model:<40} FAILED: {type(exc).__name__}: {str(exc)[:160]}")


if __name__ == "__main__":
    main()

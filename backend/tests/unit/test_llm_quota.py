"""Free-tier safety of the model layer, with a stub provider: batched extraction, the response
cache, per-minute limits and 429 retries (none of this runs with the default fake models)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from backend.app.agents.nodes import core
from backend.app.llm import factory, ratelimit
from backend.app.llm.routing import NodeRoute

DATA = Path(__file__).resolve().parents[3] / "demo_data"
SECTIONS = [{**sec, "section_path": sec.get("heading"), "tables": []}
            for doc in json.loads((DATA / "tender/TDR-001/extracted/tender_sections.json").read_text(encoding="utf-8"))
            ["documents"] for sec in doc.get("sections") or []]


class StubModel:
    """Answers like a provider: one requirement per [S<n>] section in the prompt."""

    def __init__(self, fail_with: list[Exception] | None = None):
        self.calls = 0
        self.fail_with = list(fail_with or [])

    def with_structured_output(self, *_a, **_k):
        raise NotImplementedError  # exercise the JSON path

    def invoke(self, messages):
        self.calls += 1
        if self.fail_with:
            raise self.fail_with.pop(0)
        user = messages[-1].content
        sections = [{"section": int(n), "requirements": [{"text": f"The bidder shall comply with section {n}.",
                                                          "mandatory": True}]}
                    for n in re.findall(r"\[S(\d+)\]", user)]
        return AIMessage(content=json.dumps({"sections": sections}),
                         usage_metadata={"input_tokens": len(user) // 4, "output_tokens": 50, "total_tokens": 0})


@pytest.fixture
def stub(monkeypatch, tmp_path):
    model = StubModel()
    route = NodeRoute(node="shred_requirements", model="groq:stub-model")
    monkeypatch.setattr(factory, "resolve", lambda node, tier=None: route)
    monkeypatch.setattr(factory, "_build_chat_model", lambda *a, **k: model)
    monkeypatch.setattr(factory, "_cache_path", lambda key: tmp_path / "llm" / f"{key}.json")
    return model


def _sections() -> list[dict]:
    return [s for s in SECTIONS if str(s.get("text", "")).strip()]


def test_extraction_is_batched_and_every_section_mapped(stub):
    sections = _sections()
    out = core._extract_sections(sections)
    by_model = [(sec, items) for sec, items, heuristic in out if not heuristic]
    assert len(by_model) == len(sections)  # every section answered by the model
    assert len(sections) > 80 and stub.calls <= len(sections) // 5  # a few batches, not one call per section
    assert all(items[0].text.startswith("The bidder shall") for _, items in by_model)
    # clauses the model left out come from the deterministic extractor, labelled as such
    added = [items for _, items, heuristic in out if heuristic]
    assert added and all(not i.text.startswith("The bidder shall") for items in added for i in items)


def test_identical_input_is_served_from_the_cache(stub):
    sections = _sections()[:12]
    core._extract_sections(sections)
    first = stub.calls
    core._extract_sections(sections)
    assert first > 0 and stub.calls == first  # second run: no provider calls


def test_missing_section_falls_back_to_deterministic_extractor(stub, monkeypatch):
    original = stub.invoke
    def drop_second(messages):  # the model "forgets" section 2 of each batch
        msg = original(messages)
        data = json.loads(msg.content)
        data["sections"] = [s for s in data["sections"] if s["section"] != 2]
        return AIMessage(content=json.dumps(data), usage_metadata=msg.usage_metadata)
    monkeypatch.setattr(stub, "invoke", drop_second)
    sections = _sections()[:6]
    out = core._extract_sections(sections)
    answered = {id(sec) for sec, _, heuristic in out if not heuristic}
    assert len(answered) < len(sections)  # the forgotten sections are covered by the rules instead
    assert {id(sec) for sec, _, _ in out} == {id(sec) for sec in sections}


def test_rate_limited_call_is_retried_not_fallen_back(stub, monkeypatch):
    class RateLimitError(Exception):
        pass
    stub.fail_with = [RateLimitError("Error code: 429 - Rate limit reached. Please try again in 1.5s.")]
    waits: list[float] = []
    monkeypatch.setattr(factory.time, "sleep", lambda s: waits.append(s))
    out = core._extract_sections(_sections()[:3])
    assert waits and 1.5 <= waits[0] <= 3.0  # provider's suggested delay, not a blind fallback
    assert sum(not heuristic for _, _, heuristic in out) == 3  # all three sections answered by the model


def test_per_minute_limits_make_calls_wait(monkeypatch):
    monkeypatch.setattr(ratelimit, "WINDOW_S", 0.4)
    monkeypatch.setattr(ratelimit, "limits_for", lambda model: ratelimit.Limits(rpm=2, tpm=0))
    monkeypatch.setattr(ratelimit, "_windows", {})
    slept: list[float] = []
    real_sleep = ratelimit.time.sleep
    monkeypatch.setattr(ratelimit.time, "sleep", lambda s: (slept.append(s), real_sleep(min(s, 0.05))))
    assert ratelimit.acquire("groq:x", 10) == 0.0 and ratelimit.acquire("groq:x", 10) == 0.0
    assert ratelimit.acquire("groq:x", 10) > 0  # third call within the window waits
    assert slept


def test_plan_limits_are_read_from_routing_config(monkeypatch):
    from backend.app.llm import routing
    raw = json.loads((DATA / "demo_config/llm_routing_and_budget.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(routing, "get_routing_config", lambda: routing.RoutingConfig.model_validate(raw))
    ratelimit.configured_limits.cache_clear()
    limits = ratelimit.configured_limits()
    ratelimit.configured_limits.cache_clear()
    assert limits["groq:openai/gpt-oss-20b"].tpm == 8000
    assert limits["google_genai:gemini-3-flash-preview"].rpm == 5

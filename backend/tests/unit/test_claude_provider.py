"""Claude via LangChain: no sampling parameters, room for thinking, native structured outputs, and
schemas Claude's structured-output format accepts (no network)."""
from __future__ import annotations

import pytest
from langchain_anthropic.chat_models import _convert_to_anthropic_output_config_format

from backend.app.agents.nodes.core import _BatchExtraction, _KeyFactsOut
from backend.app.agents.nodes.drafting import DraftClaimsOut
from backend.app.llm import factory
from backend.app.llm.routing import spec_from_plan
from backend.app.schemas.requirements import KeyFacts


@pytest.fixture
def claude(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    factory._build_chat_model.cache_clear()
    yield factory._build_chat_model("anthropic:claude-haiku-5-5", 0.0, None, 60.0)
    factory._build_chat_model.cache_clear()


def test_claude_gets_no_temperature_and_room_for_thinking(claude):
    assert claude.model == "claude-haiku-5-5"
    assert claude.temperature is None  # sampling parameters return a 400 since 2026-10-21
    assert claude.max_tokens == factory.ANTHROPIC_MAX_TOKENS


def test_claude_uses_native_structured_output(claude, monkeypatch):
    seen = {}
    real = type(claude).with_structured_output
    def spy(self, schema, **kw):
        seen.update(kw)
        return real(self, schema, **kw)
    monkeypatch.setattr(type(claude), "with_structured_output", spy)
    factory.structured_runnable(claude, DraftClaimsOut, "anthropic:claude-haiku-5-5")
    assert seen["method"] == "json_schema"  # not a forced tool call (rejected on current models)


@pytest.mark.parametrize("schema", [_BatchExtraction, DraftClaimsOut, _KeyFactsOut])
def test_model_facing_schemas_convert_for_claude(schema):
    assert _convert_to_anthropic_output_config_format(schema)["type"] == "json_schema"


def test_typed_key_facts_round_trip_to_key_facts():
    out = _KeyFactsOut(tender_id="T", facts=[{"name": "emd", "value": 7680000.0}])
    assert KeyFacts.model_validate(out.model_dump()).facts[0].value == 7680000.0


def test_plan_names_map_to_anthropic():
    assert spec_from_plan("claude-sonnet-5-5") == "anthropic:claude-sonnet-5-5"

"""Per-node model routing loaded from demo_config/llm_routing_and_budget.json.

Expected (tolerant) JSON shape — every key optional:
{
  "models": {"fast": "google_genai:gemini-2.0-flash", "strong": "openai:gpt-4o"},
  "nodes": {"shred_requirements": {"tier": "fast", "temperature": 0, "max_tokens": 4000}},
  "prices_per_million": {"gpt-4o": {"input": 2.5, "output": 10}},
  "budget": {"max_cost_usd": 5, "max_llm_calls": 400}
}
Environment variables (LLM_FAST / LLM_STRONG) override the file's model names.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.core.config import get_settings, load_demo_config

Tier = Literal["fast", "strong"]

DEFAULT_NODE_TIERS: dict[str, Tier] = {
    "shred_requirements": "fast",
    "extract_key_facts": "fast",
    "reconcile_corrigenda": "fast",
    "route_requirements": "fast",
    "requirement_router": "fast",
    "similarity_judge": "strong",
    "technical_grader": "strong",
    "bid_score": "fast",
    "plan_response": "strong",
    "write_sections": "strong",
    "verify_claims": "strong",
    "rewrite_failed": "strong",
    "write_no_bid_report": "fast",
    "ask_tender": "fast",
}


class NodeRoute(BaseModel):
    node: str
    tier: Tier = "fast"
    model: str
    temperature: float = 0.0
    max_tokens: int | None = None
    timeout_s: float = 60.0


class RoutingConfig(BaseModel):
    models: dict[str, str] = Field(default_factory=dict)
    nodes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Plan-style section in llm_routing_and_budget.json: node -> {"primary": "groq/openai/gpt-oss-20b", ...}
    routing: dict[str, Any] = Field(default_factory=dict)
    prices_per_million: dict[str, dict[str, float]] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)


@lru_cache
def get_routing_config() -> RoutingConfig:
    raw = load_demo_config("llm_routing_and_budget.json") or {}
    try:
        return RoutingConfig.model_validate(raw)
    except Exception:
        # tolerate unknown shapes: keep what we can
        return RoutingConfig(
            models=raw.get("models", {}) if isinstance(raw.get("models"), dict) else {},
            nodes=raw.get("nodes", {}) if isinstance(raw.get("nodes"), dict) else {},
        )


def model_for_tier(tier: Tier) -> str:
    s = get_settings()
    cfg = get_routing_config()
    env_val = s.llm_fast if tier == "fast" else s.llm_strong
    # env wins unless it is the default fake placeholder and the file names a model
    if env_val.startswith("fake:") and cfg.models.get(tier):
        return cfg.models[tier]
    return env_val


# Graph node name -> name used in the routing file.
_ROUTING_ALIASES = {"similarity_judge": "similar_work_judge", "technical_grader": "technical_grading",
                    "requirement_router": "route_requirements", "rewrite_failed": "write_sections"}


def spec_from_plan(name: str | None) -> str | None:
    """'groq/openai/gpt-oss-20b' -> 'groq:openai/gpt-oss-20b'; 'gemini-3-flash' ->
    'google_genai:gemini-3-flash'; non-model entries ('keyword rules', 'code') -> None."""
    if not name or not isinstance(name, str) or not name.strip():
        return None
    name = name.split()[0]  # drop annotations like "(10-15 items per call)"
    if ":" in name:
        return name
    if name.startswith("groq/"):
        return "groq:" + name.removeprefix("groq/")
    if name.startswith("gemini"):
        return "google_genai:" + name
    if name.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai:" + name
    return None


def planned_model(node: str) -> str | None:
    entry = get_routing_config().routing.get(_ROUTING_ALIASES.get(node, node))
    if isinstance(entry, dict):
        return spec_from_plan(entry.get("primary")) or spec_from_plan(entry.get("fallback"))
    return None


def resolve(node: str, tier: Tier | None = None) -> NodeRoute:
    """Model for a node. Offline (`fake:*` tier) stays offline; otherwise an explicit
    `nodes` entry wins, then the plan's per-node primary (e.g. Gemini for drafting),
    then the tier model from LLM_FAST / LLM_STRONG."""
    cfg = get_routing_config()
    node_cfg = cfg.nodes.get(node, {})
    t: Tier = node_cfg.get("tier") or tier or DEFAULT_NODE_TIERS.get(node, "fast")
    tier_model = model_for_tier(t)
    if tier_model.startswith("fake:"):
        model = tier_model
    else:
        model = node_cfg.get("model") or planned_model(node) or tier_model
    return NodeRoute(
        node=node, tier=t, model=model,
        temperature=float(node_cfg.get("temperature", 0.0)),
        max_tokens=node_cfg.get("max_tokens"),
        timeout_s=float(node_cfg.get("timeout_s", get_settings().llm_timeout_s)),
    )

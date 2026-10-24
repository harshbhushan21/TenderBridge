"""Model-agnostic LLM access.

Model specs are `provider:model`, e.g. `openai:gpt-4o-mini`,
`google_genai:gemini-2.0-flash`, `anthropic:claude-sonnet-5-5`, `ollama:llama3.1`.
`fake:*` (the default) means "no LLM configured": callers MUST pass a
deterministic `heuristic` so the pipeline still runs end-to-end, and results
are labelled `fallback=True`.

Usage inside a node:
    res = structured_call("shred_requirements", RequirementExtraction,
                          system=load_prompt("shredder"), user=section_text,
                          heuristic=lambda: regex_shred(section))
    extraction = res.value
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from backend.app.core.config import get_settings
from backend.app.core.errors import BudgetExceeded, ConfigError, LLMOutputError
from backend.app.core.logging import get_logger
from backend.app.llm import ratelimit
from backend.app.llm.budget import check_budget, estimate_cost, get_budget
from backend.app.llm.routing import NodeRoute, Tier, get_routing_config, resolve
from backend.app.ops.langsmith import traceable

log = get_logger(__name__)
T = TypeVar("T")
S = TypeVar("S", bound=BaseModel)

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class LLMResult(Generic[T]):
    value: T
    model: str
    fallback: bool = False          # True => heuristic produced the value (no / failed LLM)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    error: str | None = None
    cached: bool = False            # True => served from the response cache (no provider call)


def is_fake(model_spec: str) -> bool:
    return model_spec.startswith("fake")


ANTHROPIC_MAX_TOKENS = 16000


@lru_cache(maxsize=16)
def _build_chat_model(model_spec: str, temperature: float, max_tokens: int | None, timeout_s: float):
    if is_fake(model_spec):
        return None
    try:
        from langchain.chat_models import init_chat_model
    except ImportError as exc:  # pragma: no cover
        raise ConfigError("langchain is not installed") from exc
    provider: str | None
    provider, _, model = model_spec.partition(":")
    if not model:
        provider, model = None, model_spec  # let langchain infer
    kwargs: dict[str, Any] = {"temperature": temperature, "timeout": timeout_s}
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if provider == "anthropic":
        # Claude rejects temperature/top_p/top_k on every model since 2026-10-21, and adaptive
        # thinking (on by default) is billed inside max_tokens, so give it room.
        kwargs.pop("temperature", None)
        kwargs.setdefault("max_tokens", ANTHROPIC_MAX_TOKENS)
    try:
        return init_chat_model(model, model_provider=provider, **kwargs)
    except TypeError:
        kwargs.pop("timeout", None)
        return init_chat_model(model, model_provider=provider, **kwargs)


def get_chat_model(node: str, tier: Tier | None = None):
    """Return a LangChain chat model for a node, or None when fake."""
    r = resolve(node, tier)
    return _build_chat_model(r.model, r.temperature, r.max_tokens, r.timeout_s)


def get_fast_llm():
    return get_chat_model("_fast", "fast")


def get_strong_llm():
    return get_chat_model("_strong", "strong")


def get_embedding_model():
    from backend.app.retrieval.embeddings import get_embedder
    return get_embedder()


@lru_cache(maxsize=64)
def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise ConfigError(f"prompt '{name}' not found at {path}")
    return path.read_text(encoding="utf-8")


def prompt_version(name: str) -> str:
    import hashlib
    try:
        return hashlib.sha256(load_prompt(name).encode()).hexdigest()[:8]
    except ConfigError:
        return "missing"


# --------------------------------------------------------------------------- #
def _usage_from(msg: Any) -> tuple[int, int]:
    um = getattr(msg, "usage_metadata", None) or {}
    if isinstance(um, dict) and um:
        return int(um.get("input_tokens", 0)), int(um.get("output_tokens", 0))
    meta = getattr(msg, "response_metadata", {}) or {}
    tu = meta.get("token_usage") or meta.get("usage") or {}
    return int(tu.get("prompt_tokens", tu.get("input_tokens", 0)) or 0), \
        int(tu.get("completion_tokens", tu.get("output_tokens", 0)) or 0)


def _record(route: NodeRoute, node: str, in_t: int, out_t: int, latency_ms: float,
            ok: bool, error: str | None = None, *, cached: bool = False) -> None:
    cost = 0.0 if cached else estimate_cost(route.model, in_t, out_t, get_routing_config().prices_per_million)
    budget = get_budget()
    if not cached:  # a cache hit spends no quota and no budget
        budget.record(node, in_t, out_t, cost)
    try:
        from backend.app.ops.metrics import record_model_usage
        record_model_usage(run_id=budget.run_id, node=node, model=route.model, tier=route.tier,
                           input_tokens=in_t, output_tokens=out_t, cost_usd=cost or 0.0,
                           latency_ms=latency_ms, ok=ok, error=error, cached=cached)
    except Exception:  # metrics must never break a run
        pass


MAX_RATE_LIMIT_WAITS = 4


def structured_runnable(llm: Any, schema: type[BaseModel], model: str) -> Any:
    """Structured output with the provider's native JSON schema where tool calling is unreliable:
    Groq's gpt-oss can answer in prose instead of calling the tool ("Tool choice is required");
    json_schema constrains the output itself. Gemini already defaults to json_schema."""
    if model.startswith(("groq:", "anthropic:")):
        # Claude: forced tool use is rejected on current models (Sonnet 5.5, Opus 5.5) and conflicts
        # with thinking; output_config.format (structured outputs) constrains the JSON instead.
        try:
            return llm.with_structured_output(schema, method="json_schema", include_raw=True)
        except (NotImplementedError, ValueError):
            pass
    return llm.with_structured_output(schema, include_raw=True)


def _cache_key(node: str, model: str, system: str, user: str, schema: type[BaseModel]) -> str:
    blob = json.dumps([node, model, system, user, schema.__name__, schema.model_json_schema()], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    return get_settings().cache_dir / "llm" / f"{key}.json"


def _cache_get(key: str, schema: type[S]) -> S | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        return schema.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_put(key: str, value: BaseModel) -> None:
    try:
        path = _cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value.model_dump_json(), encoding="utf-8")
    except OSError as exc:  # the cache is an optimisation, never a failure
        log.warning("LLM cache write failed: %s", exc)


def _messages(system: str, user: str):
    from langchain_core.messages import HumanMessage, SystemMessage
    return [SystemMessage(content=system), HumanMessage(content=user)]


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=-1)
    if start > 0:
        text = text[start:]
    return json.loads(text)


@traceable(name="structured_call", run_type="chain")
def structured_call(node: str, schema: type[S], *, system: str, user: str,
                    heuristic: Callable[[], S] | None = None, tier: Tier | None = None) -> LLMResult[S]:
    """Call the routed model with structured output; one schema-repair retry.

    Falls back to `heuristic()` when the model is fake or both attempts fail.
    Budget exhaustion is never swallowed.
    """
    route = resolve(node, tier)
    if is_fake(route.model):
        if heuristic is None:
            raise ConfigError(f"node '{node}' needs an LLM ({route.tier}) but none is configured")
        return LLMResult(value=heuristic(), model=route.model, fallback=True)

    settings = get_settings()
    key = _cache_key(node, route.model, system, user, schema)
    cached = _cache_get(key, schema) if settings.llm_cache else None
    if cached is not None:  # identical model, prompt and input: reuse the earlier answer
        _record(route, node, 0, 0, 0.0, True, cached=True)
        return LLMResult(value=cached, model=route.model, cached=True)

    llm = _build_chat_model(route.model, route.temperature, route.max_tokens, route.timeout_s)
    max_retries = max(0, settings.max_retries)
    last_err: str | None = None
    raw_text = ""
    est_tokens = (len(system) + len(user)) // 4 + (route.max_tokens or 1024)
    attempt = 0
    rate_waits = 0
    while attempt <= max_retries:
        check_budget(node)
        ratelimit.acquire(route.model, est_tokens)
        t0 = time.perf_counter()
        in_t = out_t = 0  # an output that fails validation was still billed
        try:
            if attempt == 0:
                msgs = _messages(system, user)
            else:  # schema-repair retry
                msgs = _messages(system, f"{user}\n\nYour previous output was invalid:\n{last_err}\n"
                                         f"Return ONLY valid JSON matching this schema:\n"
                                         f"{json.dumps(schema.model_json_schema())[:6000]}")
            try:
                runnable = structured_runnable(llm, schema, route.model)
                out = runnable.invoke(msgs)
                raw_msg = out.get("raw")
                parsed = out.get("parsed")
                in_t, out_t = _usage_from(raw_msg)
                if parsed is None:
                    raw_text = getattr(raw_msg, "content", "") or ""
                    parsed = schema.model_validate(_extract_json(raw_text))
                elif not isinstance(parsed, schema):
                    parsed = schema.model_validate(parsed)
            except NotImplementedError:
                msg = llm.invoke(msgs)
                in_t, out_t = _usage_from(msg)
                raw_text = msg.content if isinstance(msg.content, str) else str(msg.content)
                parsed = schema.model_validate(_extract_json(raw_text))
            lat = (time.perf_counter() - t0) * 1000
            ratelimit.settle(route.model, in_t + out_t)
            _record(route, node, in_t, out_t, lat, True)
            if settings.llm_cache:
                _cache_put(key, parsed)
            return LLMResult(value=parsed, model=route.model, input_tokens=in_t,
                             output_tokens=out_t, latency_ms=lat)
        except BudgetExceeded:
            raise
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            last_err = str(exc)[:2000]
            ratelimit.settle(route.model, in_t + out_t)
            _record(route, node, in_t, out_t, (time.perf_counter() - t0) * 1000, False, last_err)
        except Exception as exc:  # provider/network error
            last_err = f"{type(exc).__name__}: {exc}"[:2000]
            _record(route, node, 0, 0, (time.perf_counter() - t0) * 1000, False, last_err)
            if ratelimit.is_rate_limited(exc) and rate_waits < MAX_RATE_LIMIT_WAITS:
                pause = ratelimit.retry_after_s(exc, rate_waits)
                rate_waits += 1
                log.warning("rate limited node=%s model=%s; retrying in %.1fs", node, route.model, pause)
                time.sleep(pause)
                continue  # a 429 is not a failed attempt: same request again
            log.warning("LLM call failed node=%s model=%s: %s", node, route.model, last_err)
        attempt += 1

    if heuristic is not None:
        log.warning("node=%s falling back to heuristic after LLM failure", node)
        return LLMResult(value=heuristic(), model=route.model, fallback=True, error=last_err)
    raise LLMOutputError(f"{node}: structured output invalid after retry", details={"error": last_err})


def text_call(node: str, *, system: str, user: str, heuristic: Callable[[], str] | None = None,
              tier: Tier | None = None) -> LLMResult[str]:
    route = resolve(node, tier)
    if is_fake(route.model):
        if heuristic is None:
            raise ConfigError(f"node '{node}' needs an LLM ({route.tier}) but none is configured")
        return LLMResult(value=heuristic(), model=route.model, fallback=True)
    llm = _build_chat_model(route.model, route.temperature, route.max_tokens, route.timeout_s)
    check_budget(node)
    t0 = time.perf_counter()
    try:
        msg = llm.invoke(_messages(system, user))
        in_t, out_t = _usage_from(msg)
        lat = (time.perf_counter() - t0) * 1000
        _record(route, node, in_t, out_t, lat, True)
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        return LLMResult(value=content, model=route.model, input_tokens=in_t, output_tokens=out_t,
                         latency_ms=lat)
    except BudgetExceeded:
        raise
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"[:2000]
        _record(route, node, 0, 0, (time.perf_counter() - t0) * 1000, False, err)
        if heuristic is not None:
            return LLMResult(value=heuristic(), model=route.model, fallback=True, error=err)
        raise LLMOutputError(f"{node}: LLM call failed", details={"error": err}) from exc


def llm_status() -> dict[str, Any]:
    fast, strong = resolve("_fast", "fast"), resolve("_strong", "strong")
    return {"fast": fast.model, "strong": strong.model,
            "fast_configured": not is_fake(fast.model), "strong_configured": not is_fake(strong.model)}

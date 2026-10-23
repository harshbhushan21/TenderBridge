"""Loadable deterministic rule-pack configuration.

Rule packs keep tender-family policy outside the rule implementations. A pack
is a JSON object with optional ``scoring`` and ``commercial`` sections. The
default pack is the checked-in demo policy; callers may provide another JSON
path without changing rule code.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.errors import ConfigError


def _default_path() -> Path:
    return get_settings().demo_config_dir / "bid_scoring_policy.json"


@lru_cache(maxsize=8)
def load_rule_pack(path: str | None = None) -> dict[str, Any]:
    """Load and validate a rule pack, failing explicitly for malformed JSON."""
    raw_path = path or get_settings().rule_pack_path or str(_default_path())
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (get_settings().project_root / candidate).resolve()
    if not candidate.exists() and path is None:
        candidate = (get_settings().project_root / "demo_data" / "demo_config" /
                     "bid_scoring_policy.json").resolve()
    if not candidate.exists():
        raise ConfigError(f"rule pack not found: {candidate}")
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid rule pack JSON: {candidate}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"rule pack must be a JSON object: {candidate}")
    return data

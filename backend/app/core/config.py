"""Validated application settings and root-path resolution.

All path resolution lives here so no other module needs `parents[...]` tricks.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[3] == project root
_DEFAULT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_DEFAULT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Paths ---
    project_root: Path = _DEFAULT_ROOT
    demo_data_dir: Path = Field(default=_DEFAULT_ROOT / "demo_data", alias="DEMO_DATA_DIR")
    storage_dir: Path = Field(default=_DEFAULT_ROOT / "storage", alias="STORAGE_DIR")

    # --- Database ---
    # SQLite works with zero setup; switch to postgresql+psycopg://... for pgvector.
    database_url: str = Field(
        default=f"sqlite:///{_DEFAULT_ROOT / 'storage' / 'tenderbridge.db'}",
        alias="DATABASE_URL",
    )
    checkpoint_url: str | None = Field(default=None, alias="CHECKPOINT_URL")
    rule_pack_path: str | None = Field(default=None, alias="RULE_PACK_PATH")

    # --- LLMs ---
    llm_fast: str = Field(default="fake:fast", alias="LLM_FAST")
    llm_strong: str = Field(default="fake:strong", alias="LLM_STRONG")
    llm_timeout_s: float = Field(default=60.0, alias="LLM_TIMEOUT_S")
    # Free-tier safety: per-model limits come from llm_routing_and_budget.json; these apply to
    # models it does not list (0 = unlimited). Responses are cached by content hash on disk.
    llm_rpm: int = Field(default=0, alias="LLM_RPM")
    llm_tpm: int = Field(default=0, alias="LLM_TPM")
    llm_cache: bool = Field(default=True, alias="LLM_CACHE")
    # Requirement extraction: model in batches of sections (true) or the deterministic extractor only.
    shred_with_llm: bool = Field(default=True, alias="SHRED_WITH_LLM")
    # Upper bound; each batch is also kept under a third of the model's tokens/minute (Groq 8K -> ~2.6K).
    shred_batch_tokens: int = Field(default=8000, alias="SHRED_BATCH_TOKENS")

    # --- Embeddings ---
    # "hash" = deterministic local fallback (no download). Others: "huggingface:BAAI/bge-m3",
    # "openai:text-embedding-3-small", "google_genai:models/text-embedding-004", "ollama:bge-m3"
    embedding_provider: str = Field(default="hash", alias="EMBEDDING_PROVIDER")
    embedding_dim: int = Field(default=1024, alias="EMBEDDING_DIM")
    reranker: str = Field(default="none", alias="RERANKER")  # "none" | "bge-reranker-v2-m3"

    # --- Provider secrets ---
    # Declared so values in .env are read; exported to os.environ by get_settings(), because the
    # provider SDKs (langchain-groq, langchain-google-genai, langsmith, huggingface) read only that.
    groq_api_key: SecretStr | None = Field(default=None, alias="GROQ_API_KEY")
    google_api_key: SecretStr | None = Field(default=None, alias="GOOGLE_API_KEY")
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    langsmith_api_key: SecretStr | None = Field(default=None, alias="LANGSMITH_API_KEY")
    langchain_api_key: SecretStr | None = Field(default=None, alias="LANGCHAIN_API_KEY")
    hf_token: SecretStr | None = Field(default=None, alias="HF_TOKEN")

    # --- Tracing ---
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_project: str = Field(default="tenderbridge", alias="LANGSMITH_PROJECT")

    # --- Budget ---
    max_cost_usd: float = Field(default=5.0, alias="MAX_COST_USD")
    max_llm_calls: int = Field(default=400, alias="MAX_LLM_CALLS")
    max_retries: int = Field(default=1, alias="MAX_RETRIES")
    max_rewrites: int = Field(default=2, alias="MAX_REWRITES")
    max_parallel_llm: int = Field(default=4, alias="MAX_PARALLEL_LLM")

    # --- Behaviour ---
    demo_mode: bool = Field(default=True, alias="DEMO_MODE")
    analysis_mode: Literal["focused", "full"] = Field(default="focused", alias="ANALYSIS_MODE")
    default_company_id: str = Field(default="NIMBUS-001", alias="DEFAULT_COMPANY_ID")
    cors_origins: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_json: bool = Field(default=False, alias="LOG_JSON")

    # --- Upload limits ---
    max_upload_mb: int = Field(default=50, alias="MAX_UPLOAD_MB")
    max_zip_entries: int = Field(default=200, alias="MAX_ZIP_ENTRIES")
    max_zip_uncompressed_mb: int = Field(default=300, alias="MAX_ZIP_UNCOMPRESSED_MB")

    @field_validator("demo_data_dir", "storage_dir", mode="before")
    @classmethod
    def _resolve_path(cls, v: Any) -> Path:
        p = Path(v).expanduser()
        return p if p.is_absolute() else (_DEFAULT_ROOT / p).resolve()

    @field_validator("database_url", "checkpoint_url", mode="before")
    @classmethod
    def _resolve_sqlite_path(cls, v: Any) -> Any:
        """Anchor relative SQLite paths at the project root, not the current
        working directory, so every command uses the same file on any machine."""
        if not isinstance(v, str) or not v.startswith("sqlite:///"):
            return v
        path = v.removeprefix("sqlite:///")
        if not path or path == ":memory:" or Path(path).is_absolute():
            return v
        return f"sqlite:///{(_DEFAULT_ROOT / path).resolve().as_posix()}"

    # ---- Derived paths ----
    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def uploads_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def parsed_dir(self) -> Path:
        return self.storage_dir / "parsed"

    @property
    def cache_dir(self) -> Path:
        return self.storage_dir / "cache"

    @property
    def exports_dir(self) -> Path:
        return self.storage_dir / "exports"

    @property
    def replay_dir(self) -> Path:
        return self.storage_dir / "replay"

    @property
    def company_kb_dir(self) -> Path:
        return self.demo_data_dir / "company_kb"

    @property
    def structured_facts_dir(self) -> Path:
        return self.demo_data_dir / "structured_facts"

    @property
    def demo_config_dir(self) -> Path:
        return self.demo_data_dir / "demo_config"

    @property
    def evaluation_dir(self) -> Path:
        """Gold labels. ONLY the evaluator may read from here (principle 6)."""
        return self.demo_data_dir / "evaluation"

    @property
    def tender_data_dir(self) -> Path:
        return self.demo_data_dir / "tender"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ensure_storage(self) -> None:
        for d in (self.storage_dir, self.uploads_dir, self.parsed_dir, self.cache_dir,
                  self.exports_dir, self.replay_dir):
            d.mkdir(parents=True, exist_ok=True)


# Settings field -> environment variables the SDKs read. A variable already set in the real
# environment is never overwritten.
_SECRET_ENV = {
    "groq_api_key": ("GROQ_API_KEY",),
    "google_api_key": ("GOOGLE_API_KEY",),
    "gemini_api_key": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),  # langchain-google-genai reads GOOGLE_API_KEY
    "openai_api_key": ("OPENAI_API_KEY",),
    "anthropic_api_key": ("ANTHROPIC_API_KEY",),
    "langsmith_api_key": ("LANGSMITH_API_KEY",),
    "langchain_api_key": ("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY"),
    "hf_token": ("HF_TOKEN",),
}


def export_provider_env(s: Settings) -> None:
    for field, names in _SECRET_ENV.items():
        secret = getattr(s, field)
        value = secret.get_secret_value().strip() if secret else ""
        if value:
            for name in names:
                if not os.environ.get(name):
                    os.environ[name] = value


def provider_configured(provider: str) -> bool:
    """True when the SDK for `provider` (groq, google_genai, openai, ...) will find an API key."""
    names = {"groq": ("GROQ_API_KEY",), "google_genai": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
             "openai": ("OPENAI_API_KEY",), "anthropic": ("ANTHROPIC_API_KEY",)}.get(provider)
    if names is None:  # local providers (ollama, huggingface, fake) need no key
        return True
    get_settings()  # make sure .env values were exported
    return any(os.environ.get(n) for n in names)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_storage()
    export_provider_env(s)
    return s


def load_demo_config(name: str) -> dict[str, Any] | None:
    """Read a JSON file from demo_data/demo_config. Returns None if absent.

    Never use this for `demo_scenarios.json` inside analysis agents — expected
    results there are for the demo harness only.
    """
    path = get_settings().demo_config_dir / name
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

"""Embedding providers with a zero-setup deterministic fallback.

EMBEDDING_PROVIDER:
  hash                              -> feature-hashed bag of words+bigrams (no download)
  huggingface:BAAI/bge-m3           -> sentence-transformers (local)
  openai:text-embedding-3-small     -> langchain-openai
  google_genai:models/text-embedding-004
  ollama:bge-m3
All vectors are L2-normalised and padded/truncated to EMBEDDING_DIM so the
DB column dimension stays stable.
"""
from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

log = get_logger(__name__)
_TOKEN = re.compile(r"[a-z0-9₹%]+(?:[.\-/][a-z0-9]+)*", re.I)


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def _normalise(vec: list[float], dim: int) -> list[float]:
    if len(vec) > dim:
        vec = vec[:dim]
    elif len(vec) < dim:
        vec = vec + [0.0] * (dim - len(vec))
    n = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / n for v in vec]


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


class HashEmbedder:
    """Deterministic hashing-trick embedder. Not semantic, but stable and offline;
    hybrid search (keyword + RRF) carries most of the relevance in this mode."""

    def __init__(self, dim: int):
        self.dim = dim
        self.name = f"hash-{dim}"

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        toks = tokenize(text)
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
            idx = h % self.dim
            sign = 1.0 if (h >> 63) & 1 else -1.0
            vec[idx] += sign * (1.0 + math.log(1 + len(f)) * 0.1)
        return _normalise(vec, self.dim)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class LangChainEmbedder:
    def __init__(self, inner, name: str, dim: int):
        self.inner = inner
        self.name = name
        self.dim = dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 32):
            out.extend(self.inner.embed_documents(texts[i:i + 32]))
        return [_normalise(list(v), self.dim) for v in out]

    def embed_query(self, text: str) -> list[float]:
        return _normalise(list(self.inner.embed_query(text)), self.dim)


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    spec = s.embedding_provider.strip()
    dim = s.embedding_dim
    if spec in ("", "hash", "fake"):
        return HashEmbedder(dim)
    provider, _, model = spec.partition(":")
    try:
        if provider == "huggingface":
            from langchain_huggingface import HuggingFaceEmbeddings
            inner = HuggingFaceEmbeddings(model_name=model, encode_kwargs={"normalize_embeddings": True})
        elif provider == "openai":
            from langchain_openai import OpenAIEmbeddings
            inner = OpenAIEmbeddings(model=model, dimensions=dim) if "3-" in model else OpenAIEmbeddings(model=model)
        elif provider == "google_genai":
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            inner = GoogleGenerativeAIEmbeddings(model=model)
        elif provider == "ollama":
            from langchain_ollama import OllamaEmbeddings
            inner = OllamaEmbeddings(model=model)
        else:
            raise ValueError(f"unknown embedding provider '{provider}'")
        return LangChainEmbedder(inner, spec, dim)
    except Exception as exc:
        log.warning("embedding provider %s unavailable (%s); using hash embeddings", spec, exc)
        return HashEmbedder(dim)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))

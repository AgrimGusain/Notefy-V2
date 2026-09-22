"""Configurable local embedding boundary.  No cloud call is required."""
from __future__ import annotations
from typing import Protocol
import hashlib, math, os, re

class EmbeddingProvider(Protocol):
    model: str
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...

class DisabledEmbeddingProvider:
    model = "disabled"
    def embed_documents(self, texts: list[str]) -> list[list[float]]: return []
    def embed_query(self, text: str) -> list[float]: return []

class LocalHashEmbeddingProvider:
    """Small deterministic feature embedding for a dependency-free local install.

    It combines tokens, character trigrams, and a handful of useful study-note
    synonyms.  It is intentionally replaceable by a sentence-transformer or API
    provider later through the same protocol.
    """
    model = "local-hash-v1"
    dimensions = 384
    _synonyms = {"starvation": ("wait", "waiting", "forever", "indefinitely", "blocked"), "deadlock": ("blocked", "cycle", "waiting"), "semaphore": ("lock", "mutex", "synchronization"), "paging": ("memory", "page", "virtual")}
    def _tokens(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        expanded = list(tokens)
        for key, values in self._synonyms.items():
            if key in tokens: expanded.extend(values)
            elif any(value in tokens for value in values): expanded.append(key)
        return expanded
    def embed_text(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in self._tokens(text):
            features = [token] + [token[i:i + 3] for i in range(max(0, len(token) - 2))]
            for feature in features:
                slot = int(hashlib.sha256(feature.encode("utf-8")).hexdigest()[:8], 16) % self.dimensions
                vector[slot] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector
    def embed_documents(self, texts: list[str]) -> list[list[float]]: return [self.embed_text(text) for text in texts]
    def embed_query(self, text: str) -> list[float]: return self.embed_text(text)

def get_embedding_provider() -> EmbeddingProvider:
    provider = os.getenv("EMBEDDING_PROVIDER", "local").lower()
    if provider in {"disabled", "none", "off"}: return DisabledEmbeddingProvider()
    # EMBEDDING_MODEL is reserved for a future provider adapter; the local
    # implementation remains the safe default for a local-first installation.
    return LocalHashEmbeddingProvider()

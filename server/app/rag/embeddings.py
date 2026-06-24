import hashlib
import math
import re
from typing import Protocol

_WORD = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class FakeEmbedder:
    """Deterministic hashing-trick embedder for tests/offline CI: shared tokens
    -> similar vectors, so cosine similarity is lexically meaningful. No network."""

    def __init__(self, dim: int = 256):
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in _WORD.findall(text.lower()):
            idx = int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim
            v[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class VoyageEmbedder:
    """Live Voyage embeddings. Lazy import so the package is only needed for
    real ingestion (pip install voyageai)."""

    def __init__(self, api_key: str, model: str = "voyage-3.5", dim: int = 1024):
        self.api_key = api_key
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        import voyageai

        client = voyageai.Client(api_key=self.api_key)
        return client.embed(texts, model=self.model, input_type="document").embeddings

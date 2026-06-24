import math
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class Hit:
    chunk_id: str
    score: float
    metadata: dict


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class VectorStore(Protocol):
    def add(self, ids: list[str], vectors: list[list[float]], metadatas: list[dict]) -> None:
        ...

    def search(
        self, query: list[float], k: int, where: Callable[[dict], bool] | None = None
    ) -> list[Hit]:
        ...


class InMemoryVectorStore:
    """Cosine-similarity store for tests/offline CI."""

    def __init__(self) -> None:
        self._ids: list[str] = []
        self._vecs: list[list[float]] = []
        self._meta: list[dict] = []

    def add(self, ids: list[str], vectors: list[list[float]], metadatas: list[dict]) -> None:
        self._ids.extend(ids)
        self._vecs.extend(vectors)
        self._meta.extend(metadatas)

    def search(
        self, query: list[float], k: int, where: Callable[[dict], bool] | None = None
    ) -> list[Hit]:
        scored = [
            Hit(self._ids[i], _cosine(query, self._vecs[i]), self._meta[i])
            for i in range(len(self._ids))
            if where is None or where(self._meta[i])
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]


class ChromaVectorStore:
    """Live Chroma store. Lazy import (pip install chromadb)."""

    def __init__(self, path: str = "data/chroma", collection: str = "corpus"):
        import chromadb

        self._client = chromadb.PersistentClient(path=path)
        self._col = self._client.get_or_create_collection(collection)

    def add(self, ids: list[str], vectors: list[list[float]], metadatas: list[dict]) -> None:
        self._col.add(ids=ids, embeddings=vectors, metadatas=metadatas)

    def search(
        self, query: list[float], k: int, where: Callable[[dict], bool] | None = None
    ) -> list[Hit]:
        # Chroma filters server-side via a where dict; the time-box is applied as a
        # published_ts upper bound by the retriever before calling this.
        res = self._col.query(query_embeddings=[query], n_results=k)
        hits = [
            Hit(res["ids"][0][i], 1.0 - res["distances"][0][i], res["metadatas"][0][i])
            for i in range(len(res["ids"][0]))
        ]
        return [h for h in hits if where is None or where(h.metadata)]

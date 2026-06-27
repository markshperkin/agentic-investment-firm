import math
from dataclasses import dataclass
from typing import Protocol


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


def _keep(meta: dict, ticker: str | None, max_published_ts: float | None) -> bool:
    if ticker is not None and meta.get("ticker") != ticker:
        return False
    if max_published_ts is not None and meta.get("published_ts", 0.0) > max_published_ts:
        return False
    return True


class VectorStore(Protocol):
    def add(self, ids: list[str], vectors: list[list[float]], metadatas: list[dict]) -> None:
        ...

    def search(
        self, query: list[float], k: int, *,
        ticker: str | None = None, max_published_ts: float | None = None,
    ) -> list[Hit]:
        ...

    def ids(self) -> set[str]:
        ...

    def clear(self) -> None:
        ...


class InMemoryVectorStore:
    """Cosine-similarity store for tests/offline CI. Filters by ticker + time-box
    BEFORE ranking, so the k results are the k best *eligible* chunks."""

    def __init__(self) -> None:
        self._ids: list[str] = []
        self._vecs: list[list[float]] = []
        self._meta: list[dict] = []

    def add(self, ids: list[str], vectors: list[list[float]], metadatas: list[dict]) -> None:
        self._ids.extend(ids)
        self._vecs.extend(vectors)
        self._meta.extend(metadatas)

    def search(
        self, query: list[float], k: int, *,
        ticker: str | None = None, max_published_ts: float | None = None,
    ) -> list[Hit]:
        scored = [
            Hit(self._ids[i], _cosine(query, self._vecs[i]), self._meta[i])
            for i in range(len(self._ids))
            if _keep(self._meta[i], ticker, max_published_ts)
        ]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]

    def ids(self) -> set[str]:
        return set(self._ids)

    def clear(self) -> None:
        self._ids, self._vecs, self._meta = [], [], []


class ChromaVectorStore:
    """Live Chroma store. Lazy import (pip install chromadb). The ticker + time-box
    filter is pushed into Chroma's native `where` so it runs BEFORE top-k — otherwise
    we'd rank the whole collection and only then drop the wrong ticker/future chunks."""

    def __init__(self, path: str = "data/chroma", collection: str = "corpus"):
        import chromadb

        self._client = chromadb.PersistentClient(path=path)
        self._col = self._client.get_or_create_collection(collection)

    def add(self, ids: list[str], vectors: list[list[float]], metadatas: list[dict]) -> None:
        self._col.add(ids=ids, embeddings=vectors, metadatas=metadatas)

    def search(
        self, query: list[float], k: int, *,
        ticker: str | None = None, max_published_ts: float | None = None,
    ) -> list[Hit]:
        clauses: list[dict] = []
        if ticker is not None:
            clauses.append({"ticker": {"$eq": ticker}})
        if max_published_ts is not None:
            clauses.append({"published_ts": {"$lte": max_published_ts}})
        where = clauses[0] if len(clauses) == 1 else ({"$and": clauses} if clauses else None)

        res = self._col.query(query_embeddings=[query], n_results=k, where=where)
        return [
            Hit(res["ids"][0][i], 1.0 - res["distances"][0][i], res["metadatas"][0][i])
            for i in range(len(res["ids"][0]))
        ]

    def ids(self) -> set[str]:
        return set(self._col.get(include=[])["ids"])

    def clear(self) -> None:
        name = self._col.name
        self._client.delete_collection(name)
        self._col = self._client.get_or_create_collection(name)

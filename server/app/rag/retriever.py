from dataclasses import dataclass
from datetime import datetime

from app.db import SessionLocal
from app.guardrails.lookahead import assert_no_lookahead
from app.models.corpus import Chunk
from app.rag.embeddings import Embedder
from app.rag.vector_store import VectorStore


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    source: str
    form_type: str
    published_date: str
    published_ts: float
    score: float


class Retriever:
    def __init__(self, embedder: Embedder, store: VectorStore):
        self.embedder = embedder
        self.store = store

    def retrieve(self, query: str, ticker: str, as_of: datetime, k: int = 5) -> list[RetrievedChunk]:
        as_of_ts = as_of.timestamp()
        qvec = self.embedder.embed([query])[0]

        def where(meta: dict) -> bool:
            return meta.get("ticker") == ticker and meta.get("published_ts", 0) <= as_of_ts

        hits = self.store.search(qvec, k, where=where)

        out: list[RetrievedChunk] = []
        with SessionLocal() as s:
            for h in hits:
                chunk = s.get(Chunk, h.chunk_id)
                if chunk is None:
                    continue
                out.append(RetrievedChunk(
                    chunk_id=h.chunk_id, text=chunk.text, source=h.metadata.get("source", ""),
                    form_type=h.metadata.get("form_type", ""),
                    published_date=h.metadata.get("published_date", ""),
                    published_ts=h.metadata.get("published_ts", 0.0), score=round(h.score, 4),
                ))

        # Independent boundary assertion — holds on every path, not just retrieval.
        assert_no_lookahead([{"chunk_id": c.chunk_id, "published_ts": c.published_ts} for c in out], as_of_ts)
        return out

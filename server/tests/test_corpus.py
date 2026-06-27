from datetime import datetime

import pytest

from app.guardrails.lookahead import LookaheadViolation, assert_no_lookahead
from app.rag.edgar import FakeFilingSource, RawFiling
from app.rag.embeddings import FakeEmbedder
from app.rag.ingest import CorpusIngester
from app.rag.retriever import Retriever
from app.rag.vector_store import InMemoryVectorStore

FILINGS = [
    RawFiling("NVDA", "8-K", "http://edgar/a",
              datetime(2024, 5, 20, 16, 30),
              "Nvidia reports record data center revenue and raises guidance for the quarter."),
    RawFiling("NVDA", "8-K", "http://edgar/b",
              datetime(2024, 5, 23, 14, 0),
              "Nvidia announces a brand new chip architecture at its developer conference."),
]


def _build():
    embedder = FakeEmbedder()
    store = InMemoryVectorStore()
    ing = CorpusIngester(FakeFilingSource(FILINGS), embedder, store)
    ing.ingest("2024-05-23", ["NVDA"])
    return Retriever(embedder, store)


def test_ingest_persists_documents_and_chunks():
    _build()
    from app.db import SessionLocal
    from app.models.corpus import Chunk, Document

    with SessionLocal() as s:
        assert s.query(Document).count() == 2
        assert s.query(Chunk).count() >= 2


def test_retrieval_is_time_boxed():
    retriever = _build()
    # at 10:00 the 14:00 filing does not exist yet -> only filing A is retrievable
    early = retriever.retrieve("data center revenue guidance", "NVDA",
                               datetime(2024, 5, 23, 10, 0), k=5)
    assert early and all(c.published_date.startswith("2024-05-20") for c in early)

    # later in the day both are eligible; the conference filing becomes retrievable
    late = retriever.retrieve("new chip architecture conference", "NVDA",
                              datetime(2024, 5, 23, 15, 0), k=5)
    assert any(c.published_date.startswith("2024-05-23") for c in late)


def test_lookahead_guardrail_raises():
    with pytest.raises(LookaheadViolation):
        assert_no_lookahead(
            [{"chunk_id": "x", "published_ts": datetime(2024, 5, 23, 14, 0).timestamp()}],
            as_of_ts=datetime(2024, 5, 23, 10, 0).timestamp(),
        )

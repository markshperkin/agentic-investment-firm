import threading
import time
from datetime import datetime

import pandas as pd

from app.data import price_feed
from app.data.prices import PriceIngester
from app.db import SessionLocal
from app.firm.hitl import resolve_approval
from app.firm.runner import run_replay
from app.llm.router import LLMRouter
from app.models.approval import ApprovalRequest
from app.models.portfolio import Trade
from app.obs.spans import set_tick
from app.rag.edgar import FakeFilingSource, RawFiling
from app.rag.embeddings import FakeEmbedder
from app.rag.ingest import CorpusIngester
from app.rag.retriever import Retriever
from app.rag.vector_store import InMemoryVectorStore

from eval.provider import EvalProvider

DATE = "2025-05-29"


def _setup(tmp_path, monkeypatch):
    price_feed.clear_cache()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    set_tick(None)

    def fetch(t, s, e, i):
        return pd.DataFrame({"ts": [datetime(2025, 5, 29, 9, 30), datetime(2025, 5, 29, 15, 30)],
                             "open": [100, 100], "high": [101, 101], "low": [99, 99],
                             "close": [100.0, 100.0], "volume": [1, 1]})
    PriceIngester(fetch=fetch, prices_dir=tmp_path).ingest(DATE, ["NVDA"])

    emb, store = FakeEmbedder(), InMemoryVectorStore()
    CorpusIngester(FakeFilingSource([RawFiling("NVDA", "8-K", "u", datetime(2025, 5, 28, 16, 0),
                                               "Revenue up strongly.")]), emb, store).ingest(DATE, ["NVDA"])
    return Retriever(emb, store)


def test_run_blocks_then_resumes_on_approval(tmp_path, monkeypatch):
    """A ≥$25k buy pauses the run; an out-of-band approval unblocks it and the
    position fills mid-run (proving the day actually waited)."""
    retriever = _setup(tmp_path, monkeypatch)

    seen = {}

    def approver():
        for _ in range(200):  # ~10s budget
            with SessionLocal() as s:
                appr = s.query(ApprovalRequest).filter_by(status="PENDING").first()
                aid = appr.id if appr else None
            if aid:
                resolve_approval(aid, decision="approve", approver="committee")
                seen["approved"] = aid
                return
            time.sleep(0.05)

    th = threading.Thread(target=approver)
    th.start()
    run_replay(DATE, ["NVDA"], retriever=retriever,
               router=LLMRouter(provider=EvalProvider()), block_on_approval=True)
    th.join(timeout=15)

    assert "approved" in seen, "run never produced a PENDING approval to wait on"
    with SessionLocal() as s:
        assert s.query(Trade).filter_by(status="FILLED").count() >= 1


def test_non_blocking_run_does_not_wait(tmp_path, monkeypatch):
    """With block_on_approval=False the same ≥$25k buy just queues — the run finishes
    fast with a PENDING approval and no fill."""
    retriever = _setup(tmp_path, monkeypatch)

    run_replay(DATE, ["NVDA"], retriever=retriever,
               router=LLMRouter(provider=EvalProvider()), block_on_approval=False)

    with SessionLocal() as s:
        assert s.query(ApprovalRequest).filter_by(status="PENDING").count() >= 1
        assert s.query(Trade).filter_by(status="FILLED").count() == 0

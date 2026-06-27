from datetime import datetime

import pandas as pd

from app.firm.pipeline import process_ticker
from app.llm.base import ProviderResult
from app.llm.router import LLMRouter
from app.obs.spans import start_run
from app.rag.edgar import FakeFilingSource, RawFiling
from app.rag.embeddings import FakeEmbedder
from app.rag.ingest import CorpusIngester
from app.rag.retriever import Retriever
from app.rag.vector_store import InMemoryVectorStore
from app.data import price_feed
from app.data.prices import PriceIngester


def _retriever():
    embedder = FakeEmbedder()
    store = InMemoryVectorStore()
    filings = [RawFiling("NVDA", "8-K", "http://e/a", datetime(2024, 5, 20, 16, 0),
                         "Nvidia reported data center revenue of 22.6 billion, up sharply.")]
    CorpusIngester(FakeFilingSource(filings), embedder, store).ingest("2024-05-23", ["NVDA"])
    return Retriever(embedder, store)


def _prices(tmp_path):
    def fetch(t, s, e, i):
        return pd.DataFrame({"ts": [datetime(2024, 5, 23, 9, 30)], "open": [100], "high": [101],
                             "low": [99], "close": [100.0], "volume": [1000]})
    PriceIngester(fetch=fetch, prices_dir=tmp_path).ingest("2024-05-23", ["NVDA"])


# scripted: query_gen, critic(good), research(view), pm(buy)
SCRIPT = [
    {"queries": ["nvidia data center revenue"], "strategy": "BASELINE"},
    {"relevant": True, "coverage": 0.9, "failure_kind": "NONE"},
    {"ticker": "NVDA", "stance": "BULLISH", "confidence": 0.8,
     "key_points": [{"text": "Data center revenue 22.6 billion.", "citation": {"chunk_id": "PLACEHOLDER"}}]},
    {"action": "BUY", "thesis_card": {"headline": "NVDA", "why_now": "earnings", "expected_edge": "x",
                                      "risks": "y", "confidence": 0.8, "key_evidence": []}},
    {"decision": "REQUIRE_HUMAN", "reasoning": "large position", "severity": "MEDIUM"},
]


class _Scripted:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    def complete(self, model, system, prompt, schema):
        return ProviderResult(data=self.payloads.pop(0), prompt_tokens=1, completion_tokens=1)


def test_context_build_produces_pending_approval(tmp_path, monkeypatch):
    start_run("test")
    price_feed.clear_cache()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    _prices(tmp_path)
    retriever = _retriever()

    # fix the research citation to a real retrieved chunk id
    chunks = retriever.retrieve("nvidia data center revenue", "NVDA", datetime(2024, 5, 23, 10, 0))
    SCRIPT[2]["key_points"][0]["citation"]["chunk_id"] = chunks[0].chunk_id

    router = LLMRouter(provider=_Scripted(SCRIPT))
    out = process_ticker(run_id="r1", ticker="NVDA", as_of=datetime(2024, 5, 23, 10, 0),
                         tick_seq=0, dispatch_path="CONTEXT_BUILD", retriever=retriever, router=router)

    assert out["outcome"] == "awaiting_approval"

    from app.firm.hitl import resolve_approval
    res = resolve_approval(out["approval_id"], decision="approve", approver="mark")
    assert res["status"] == "APPROVED"
    assert res["fill"]["status"] == "FILLED"

from datetime import datetime

import pandas as pd

from app.data import price_feed
from app.data.prices import PriceIngester
from app.db import SessionLocal
from app.llm.base import ProviderResult
from app.llm.router import LLMRouter
from app.models.span import Span
from app.rag.chunker import chunk_text
from app.rag.crag import run_crag
from app.rag.edgar import FakeFilingSource, RawFiling
from app.rag.ingest import CorpusIngester
from app.rag.retriever import Retriever
from app.rag.vector_store import InMemoryVectorStore
from app.firm.runner import run_replay
from app.obs.spans import set_tick


class _Scripted:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    def complete(self, model, system, prompt, schema):
        return ProviderResult(data=self.payloads.pop(0), prompt_tokens=1, completion_tokens=1)


class _RecordingEmbedder:
    dim = 4

    def __init__(self):
        self.calls: list[str] = []

    def embed(self, texts, input_type: str = "document"):
        self.calls.append(input_type)
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


# R1 — the query is embedded as a QUERY, the chunks as DOCUMENTS
def test_query_embedded_with_query_input_type():
    rec = _RecordingEmbedder()
    store = InMemoryVectorStore()
    filings = [RawFiling("NVDA", "8-K", "u", datetime(2025, 5, 28, 16, 0),
                         "Data center revenue up 142 percent.")]
    CorpusIngester(FakeFilingSource(filings), rec, store).ingest("2025-05-29", ["NVDA"])
    assert rec.calls and set(rec.calls) == {"document"}

    Retriever(rec, store).retrieve("revenue growth", "NVDA", datetime(2025, 5, 29, 10, 0))
    assert rec.calls[-1] == "query"


# R2 — the store filters ticker + time-box BEFORE ranking
def test_store_filters_before_topk():
    store = InMemoryVectorStore()
    store.add(
        ["nvda_old", "nvda_future", "aapl"],
        [[1, 0, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0]],
        [
            {"ticker": "NVDA", "published_ts": 100.0},
            {"ticker": "NVDA", "published_ts": 999.0},   # after as_of -> excluded
            {"ticker": "AAPL", "published_ts": 100.0},   # wrong ticker -> excluded
        ],
    )
    hits = store.search([1, 0, 0, 0], k=8, ticker="NVDA", max_published_ts=500.0)
    assert [h.chunk_id for h in hits] == ["nvda_old"]


# R3 — chunk size default is 5000 / 800 overlap
def test_chunk_size_default():
    text = "word " * 4000  # ~20k chars
    chunks = chunk_text(text)
    assert max(len(c) for c in chunks) <= 5000
    assert any(len(c) > 800 for c in chunks)  # not the old tiny chunks


# R4 — CRAG accepts on coverage even when the critic says not-relevant
def test_crag_accepts_on_coverage():
    embedder, store = _RecordingEmbedder(), InMemoryVectorStore()
    filings = [RawFiling("NVDA", "8-K", "u", datetime(2025, 5, 28, 16, 0), "Revenue up sharply.")]
    CorpusIngester(FakeFilingSource(filings), embedder, store).ingest("2025-05-29", ["NVDA"])
    retriever = Retriever(embedder, store)

    plan = {"queries": ["nvda revenue"], "strategy": "BASELINE"}
    grade = {"relevant": False, "coverage": 0.5, "failure_kind": "NONE"}  # not relevant, but enough
    router = LLMRouter(provider=_Scripted([plan, grade]))

    res = run_crag(ticker="NVDA", as_of=datetime(2025, 5, 29, 10, 0), intent="RESEARCH_ENTRY",
                   retriever=retriever, router=router)
    assert res.status == "OK"


# R5 — the benchmark (SPY) is excluded from the traded universe
def test_spy_excluded_from_run(tmp_path, monkeypatch):
    from eval.provider import EvalProvider

    price_feed.clear_cache()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    set_tick(None)

    def fetch(t, s, e, i):
        return pd.DataFrame({"ts": [datetime(2025, 5, 29, 9, 30), datetime(2025, 5, 29, 15, 30)],
                             "open": [100, 100], "high": [101, 101], "low": [99, 99],
                             "close": [100.0, 100.0], "volume": [1, 1]})
    PriceIngester(fetch=fetch, prices_dir=tmp_path).ingest("2025-05-29", ["NVDA"])  # adds SPY too

    embedder, store = _RecordingEmbedder(), InMemoryVectorStore()
    filings = [RawFiling("NVDA", "8-K", "u", datetime(2025, 5, 28, 16, 0), "Revenue up.")]
    CorpusIngester(FakeFilingSource(filings), embedder, store).ingest("2025-05-29", ["NVDA"])
    retriever = Retriever(embedder, store)

    run_id = run_replay("2025-05-29", ["NVDA", "SPY"], retriever=retriever,
                        router=LLMRouter(provider=EvalProvider()), block_on_approval=False)

    with SessionLocal() as s:
        agents = s.query(Span).filter(Span.run_id == run_id, Span.kind == "AGENT").all()
    tickers = {a.ticker for a in agents if a.ticker}
    assert "SPY" not in tickers
    assert "NVDA" in tickers

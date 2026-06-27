from datetime import datetime

import pandas as pd

from app.data import price_feed
from app.data.prices import PriceIngester
from app.db import SessionLocal
from app.firm import memory
from app.firm.monitor import process_monitor_sell, process_day_review, stop_triggers
from app.firm.pipeline import process_incremental_news, process_price_reeval
from app.llm.base import ProviderResult
from app.llm.router import LLMRouter
from app.models.corpus import Chunk
from app.obs.spans import set_tick, start_run
from app.rag.edgar import FakeFilingSource, RawFiling
from app.rag.embeddings import FakeEmbedder
from app.rag.ingest import CorpusIngester
from app.rag.retriever import Retriever
from app.rag.vector_store import InMemoryVectorStore
from app.state.broker import PaperBroker


class _Scripted:
    def __init__(self, payloads):
        self.payloads = list(payloads)

    def complete(self, model, system, prompt, schema):
        return ProviderResult(data=self.payloads.pop(0), prompt_tokens=1, completion_tokens=1)


def _ingest_news(replay_date, published):
    embedder, store = FakeEmbedder(), InMemoryVectorStore()
    filings = [RawFiling("NVDA", "8-K", "http://e/a", published,
                         "Nvidia reported data center revenue of 22.6 billion, up sharply.")]
    CorpusIngester(FakeFilingSource(filings), embedder, store).ingest(replay_date, ["NVDA"])
    return Retriever(embedder, store)


def _prices(tmp_path, replay_date, close=100.0):
    def fetch(t, s, e, i):
        return pd.DataFrame({"ts": [datetime(2024, 5, 23, 9, 30)], "open": [close], "high": [close + 1],
                             "low": [close - 1], "close": [close], "volume": [1000]})
    PriceIngester(fetch=fetch, prices_dir=tmp_path).ingest(replay_date, ["NVDA"])


def _chunk_id():
    with SessionLocal() as s:
        return s.query(Chunk).filter(Chunk.ticker == "NVDA").first().id


def _bullish_view_payload(chunk_id):
    return {"ticker": "NVDA", "stance": "BULLISH", "confidence": 0.8,
            "key_points": [{"text": "Data center revenue 22.6 billion.",
                            "citation": {"chunk_id": chunk_id}}]}


def test_incremental_news_skips_crag_and_proposes(tmp_path, monkeypatch):
    start_run("t")
    set_tick(1)
    price_feed.clear_cache()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    _prices(tmp_path, "2024-05-23")
    _ingest_news("2024-05-23", datetime(2024, 5, 23, 10, 30))  # filing lands mid-day

    research = _bullish_view_payload(_chunk_id())
    pm = {"action": "BUY", "thesis_card": {"headline": "NVDA", "why_now": "earnings",
          "expected_edge": "x", "risks": "y", "confidence": 0.8, "key_evidence": []}}
    risk = {"decision": "REQUIRE_HUMAN", "reasoning": "large", "severity": "MEDIUM"}
    router = LLMRouter(provider=_Scripted([research, pm, risk]))  # NOTE: no query_gen/critic = CRAG skipped

    out = process_incremental_news(run_id="t", ticker="NVDA", as_of=datetime(2024, 5, 23, 11, 0),
                                   tick_seq=1, last_as_of=datetime(2024, 5, 23, 10, 0), router=router)
    assert out["outcome"] == "awaiting_approval"
    # dedup: same window again finds nothing new
    out2 = process_incremental_news(run_id="t", ticker="NVDA", as_of=datetime(2024, 5, 23, 12, 0),
                                    tick_seq=2, last_as_of=datetime(2024, 5, 23, 11, 0), router=router)
    assert out2["outcome"] == "no_new_docs"


def test_price_reeval_reuses_cached_view(tmp_path, monkeypatch):
    start_run("t")
    set_tick(3)
    price_feed.clear_cache()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    _prices(tmp_path, "2024-05-23")
    cid = "doc:0"
    memory.record(run_id="t", ticker="NVDA", tick_seq=0, as_of="2024-05-23T10:00:00",
                  stance="BULLISH", confidence=0.8,
                  current_view={"ticker": "NVDA", "stance": "BULLISH", "confidence": 0.8,
                                "key_points": [{"text": "rev 22.6 billion",
                                                "citation": {"chunk_id": cid}}]},
                  open_thesis="t", position_qty=0, cost_basis=0.0, last_decision_price=100.0,
                  processed_doc_ids=["doc"], decision_log=[], dispatch_path="CONTEXT_BUILD")

    pm = {"action": "BUY", "thesis_card": {"headline": "NVDA", "why_now": "move",
          "expected_edge": "x", "risks": "y", "confidence": 0.8, "key_evidence": []}}
    risk = {"decision": "REQUIRE_HUMAN", "reasoning": "large", "severity": "MEDIUM"}
    router = LLMRouter(provider=_Scripted([pm, risk]))  # NOTE: no research call = view reused

    out = process_price_reeval(run_id="t", ticker="NVDA", as_of=datetime(2024, 5, 23, 13, 0),
                               tick_seq=3, router=router)
    assert out["outcome"] == "awaiting_approval"


def test_stop_loss_triggers_protective_sell(tmp_path, monkeypatch):
    start_run("t")
    set_tick(2)
    price_feed.clear_cache()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    _prices(tmp_path, "2024-05-23", close=90.0)  # current price 90
    # buy 100 @ ~100 cost basis
    PaperBroker().execute(ticker="NVDA", side="BUY", quantity=100, reference_price=100.0,
                          as_of=datetime(2024, 5, 23, 10, 0))

    triggers = stop_triggers(["NVDA"], "2024-05-23", datetime(2024, 5, 23, 14, 0))
    assert triggers and triggers[0]["kind"] == "STOP_LOSS"

    out = process_monitor_sell(run_id="t", ticker="NVDA", as_of=datetime(2024, 5, 23, 14, 0),
                               tick_seq=2, trigger=triggers[0])
    assert out["outcome"] == "protective_sell"

    from app.state.portfolio import account_snapshot
    assert account_snapshot("NVDA", 90.0)["position_qty"] == 0


def test_day_review_flatten_closes_position(tmp_path, monkeypatch):
    start_run("t")
    set_tick(6)
    price_feed.clear_cache()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    _prices(tmp_path, "2024-05-23", close=101.0)
    PaperBroker().execute(ticker="NVDA", side="BUY", quantity=50, reference_price=100.0,
                          as_of=datetime(2024, 5, 23, 10, 0))

    eod = {"action": "FLATTEN", "reasoning": "gap risk into close", "gap_risk": "HIGH"}
    router = LLMRouter(provider=_Scripted([eod]))
    out = process_day_review(run_id="t", ticker="NVDA", as_of=datetime(2024, 5, 23, 15, 30),
                             tick_seq=6, last_as_of=datetime(2024, 5, 23, 14, 30),
                             retriever=None, router=router)
    assert out["eod_action"] == "FLATTEN"

    from app.state.portfolio import account_snapshot
    assert account_snapshot("NVDA", 101.0)["position_qty"] == 0

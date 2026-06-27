"""End-to-end validation of the demo dataset: one scripted NVDA day must fire every
dispatch path in order. Deterministic — a per-tick scripted provider stands in for
the live model, and the approval threshold is raised so the HITL buys auto-fill so
the run stays single-threaded. (The HITL pause itself is covered by test_risk_hitl.)"""
from pathlib import Path

import pytest

from app.config import get_settings
from app.data import price_feed
from app.data.demo_dataset import (
    DEMO_ARTICLES,
    DEMO_DATE,
    DEMO_ENTRY_8K,
    demo_price_fetch,
)
from app.data.prices import PriceIngester
from app.db import SessionLocal
from app.firm.runner import run_replay
from app.llm.base import ProviderResult
from app.llm.router import LLMRouter
from app.models.portfolio import Trade
from app.models.span import Span
from app.rag.edgar import FakeFilingSource
from app.rag.embeddings import FakeEmbedder
from app.rag.ingest import CorpusIngester
from app.rag.retriever import Retriever
from app.rag.vector_store import InMemoryVectorStore

from eval.provider import _first_chunk_id, _ticker
from eval.scenarios import _clean

# Key off the genuinely bearish article's distinctive language ("sharply curtail",
# "came under immediate pressure") — NOT "export"/"curb", which the bullish T6 rebuttal
# also uses. Mirrors live Claude flipping bearish only on the export-curb report itself.
_BEARISH = ("curtail", "came under")
_FLATTEN = ("overnight gap", "reducing exposure")


class DemoProvider:
    """Scripted model keyed off prompt content: bullish by default, bearish when the
    export-curbs article is in view, and FLATTEN at the close when the gap article is."""

    def complete(self, model, system, prompt, schema) -> ProviderResult:
        return ProviderResult(data=self._data(schema.__name__, prompt),
                              prompt_tokens=10, completion_tokens=10)

    def _data(self, name: str, prompt: str) -> dict:
        low = prompt.lower()
        if name == "QueryPlan":
            return {"queries": [f"{_ticker(prompt)} fundamentals"], "strategy": "BASELINE"}
        if name == "RelevanceGrade":
            return {"relevant": True, "coverage": 0.9, "failure_kind": "NONE", "fix_hint": ""}
        if name == "ResearchView":
            bearish = any(k in low for k in _BEARISH)
            return {
                "ticker": _ticker(prompt),
                "stance": "BEARISH" if bearish else "BULLISH",
                "confidence": 0.8,
                "key_points": [{"text": "Thesis grounded in the latest filing.",
                                "citation": {"chunk_id": _first_chunk_id(prompt)}}],
            }
        if name == "PMDecision":
            action = "SELL" if "stance: bearish" in low else "BUY"
            return {"action": action,
                    "thesis_card": {"headline": "thesis", "why_now": "catalyst",
                                    "expected_edge": "edge", "risks": "macro",
                                    "confidence": 0.8, "key_evidence": []},
                    "stop_loss_pct": 0.04, "take_profit_pct": 0.10}
        if name == "RiskNarrative":
            return {"decision": "REQUIRE_HUMAN", "reasoning": "sizeable entry", "severity": "MEDIUM"}
        if name == "EodDecision":
            flatten = any(k in low for k in _FLATTEN)
            return {"action": "FLATTEN" if flatten else "HOLD",
                    "reasoning": "overnight gap risk" if flatten else "thesis intact",
                    "gap_risk": "HIGH" if flatten else "LOW"}
        if name == "ReportSummary":
            return {"headline": "EOD", "summary": "summary", "risk_note": "none"}
        raise ValueError(f"DemoProvider has no canned response for {name}")


def _tick_paths(run_id: str) -> list[str]:
    with SessionLocal() as s:
        rows = s.query(Span).filter(Span.run_id == run_id, Span.kind == "TICK").order_by(
            Span.started_at.asc()).all()
        return [r.name for r in rows]


def _fills(run_id: str) -> list[Trade]:
    with SessionLocal() as s:
        rows = s.query(Trade).filter(Trade.run_id == run_id, Trade.status == "FILLED").order_by(
            Trade.as_of.asc(), Trade.filled_at.asc()).all()
        return [(t.side, t.as_of, t.realized_pnl) for t in rows]


@pytest.fixture
def demo_world(tmp_path, monkeypatch):
    _clean()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    # Raise the HITL threshold so the buys auto-fill inline (keeps the test single-threaded).
    monkeypatch.setattr(get_settings(), "approval_notional_threshold", 10_000_000.0)

    PriceIngester(fetch=demo_price_fetch, prices_dir=tmp_path).ingest(DEMO_DATE, ["NVDA"])

    embedder, store = FakeEmbedder(), InMemoryVectorStore()
    filings = [DEMO_ENTRY_8K, *DEMO_ARTICLES]
    CorpusIngester(FakeFilingSource(filings), embedder, store).ingest(DEMO_DATE, ["NVDA"])
    return Retriever(embedder, store)


def test_demo_day_fires_every_path(demo_world):
    retriever = demo_world
    run_id = run_replay(DEMO_DATE, ["NVDA"], retriever=retriever,
                        router=LLMRouter(provider=DemoProvider()), block_on_approval=False)

    paths = _tick_paths(run_id)
    # 8 ticks + the trailing REPORT tick.
    assert paths == [
        "CONTEXT_BUILD",     # T0 open -> buy
        "MONITOR_SELL",      # T1 take-profit
        "INCREMENTAL_NEWS",  # T2 re-buy
        "MONITOR_SELL",      # T3 stop-loss
        "INCREMENTAL_NEWS",  # T4 re-buy
        "INCREMENTAL_NEWS",  # T5 news-driven sell
        "INCREMENTAL_NEWS",  # T6 re-buy
        "DAY_REVIEW",        # T7 flatten
        "REPORT",
    ]


def test_demo_day_trades(demo_world):
    retriever = demo_world
    run_id = run_replay(DEMO_DATE, ["NVDA"], retriever=retriever,
                        router=LLMRouter(provider=DemoProvider()), block_on_approval=False)

    fills = _fills(run_id)
    sides = [side for side, _, _ in fills]
    # four entries and four exits, strictly alternating
    assert sides == ["BUY", "SELL", "BUY", "SELL", "BUY", "SELL", "BUY", "SELL"]

    realized = [pnl for side, _, pnl in fills if side == "SELL"]
    assert realized[0] > 0    # T1 take-profit books a gain
    assert realized[1] < 0    # T3 stop-loss books a loss
    assert len(realized) == 4

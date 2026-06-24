from app.agents.pm import PMAgent
from app.agents.schemas import Citation, KeyPoint, ResearchView
from app.firm import memory
from app.llm.base import ProviderResult
from app.llm.router import LLMRouter
from app.obs.spans import start_run
from app.state.sizing import position_sizer


def test_sizer_scales_with_confidence_and_clamps():
    # equity 1,000,000 * 10% * confidence 0.8 = 80,000 -> capped at 25,000 notional
    qty = position_sizer(confidence=0.8, equity=1_000_000, price=100.0, cash=1_000_000,
                         max_position_pct=0.10, max_order_notional=25_000)
    assert qty == 250  # 25,000 / 100
    # cash-constrained
    qty2 = position_sizer(confidence=1.0, equity=1_000_000, price=100.0, cash=5_000,
                          max_position_pct=0.10, max_order_notional=25_000)
    assert qty2 == 50


def _view(stance="BULLISH", conf=0.8):
    return ResearchView(ticker="NVDA", stance=stance, confidence=conf,
                        key_points=[KeyPoint(text="Strong revenue.", citation=Citation(chunk_id="d:0"))])


class _Scripted:
    def __init__(self, data):
        self.data = data

    def complete(self, model, system, prompt, schema):
        return ProviderResult(data=self.data, prompt_tokens=1, completion_tokens=1)


def test_pm_no_trade_below_confidence():
    start_run("test")
    pm = PMAgent(LLMRouter(provider=_Scripted({})))
    out = pm.decide(_view(conf=0.3), equity=1_000_000, cash=1_000_000, price=100.0)
    assert out.__class__.__name__ == "NoTrade"


def test_pm_buy_proposal():
    start_run("test")
    payload = {
        "action": "BUY",
        "thesis_card": {"headline": "NVDA momentum", "why_now": "earnings beat",
                        "expected_edge": "rerating", "risks": "valuation", "confidence": 0.8,
                        "key_evidence": [{"chunk_id": "d:0"}]},
    }
    pm = PMAgent(LLMRouter(provider=_Scripted(payload)))
    out = pm.decide(_view(), equity=1_000_000, cash=1_000_000, price=100.0)
    assert out.__class__.__name__ == "TradeProposal"
    assert out.side == "BUY" and out.quantity == 250


def test_ticker_memory_is_append_only_timeline():
    start_run("test")
    for i, (stance, conf) in enumerate([("NEUTRAL", 0.4), ("BULLISH", 0.7)]):
        memory.record(run_id="r1", ticker="NVDA", tick_seq=i, as_of=f"t{i}", stance=stance,
                      confidence=conf, current_view=None, open_thesis=None, position_qty=0,
                      cost_basis=0.0, last_decision_price=None, processed_doc_ids=[],
                      decision_log=[], dispatch_path="CONTEXT_BUILD")
    latest = memory.latest("r1", "NVDA")
    assert latest.stance == "BULLISH" and latest.tick_seq == 1

from datetime import datetime

from app.agents.schemas import ThesisCard, TradeProposal
from app.config import get_settings
from app.firm.hitl import resolve_approval, submit_for_approval
from app.guardrails import risk_engine
from app.obs.spans import start_run

S = get_settings()


def _eval(side="BUY", quantity=100, price=100.0, equity=1_000_000, cash=1_000_000,
          position_qty=0, position_value=0.0):
    return risk_engine.evaluate(
        side=side, quantity=quantity, price=price, equity=equity, cash=cash,
        position_qty=position_qty, position_value=position_value,
        trades_today=0, day_pnl_pct=0.0, settings=S,
    )


def test_engine_rejects_oversized_order():
    # 1000 * 100 = 100,000 > 25,000 cap
    assert _eval(quantity=1000).decision == "REJECT"


def test_engine_requires_human_for_legal_buy():
    assert _eval(quantity=100).decision == "REQUIRE_HUMAN"  # 10,000 notional, within caps


def test_engine_auto_approves_risk_reducing_sell():
    assert _eval(side="SELL", quantity=10, position_qty=50).decision == "AUTO_APPROVE"


def test_engine_rejects_oversell():
    assert _eval(side="SELL", quantity=100, position_qty=10).decision == "REJECT"


def _proposal():
    return TradeProposal(
        ticker="NVDA", side="BUY", quantity=100, est_notional=10_000.0,
        thesis_card=ThesisCard(headline="h", why_now="w", expected_edge="e", risks="r",
                               confidence=0.8),
    )


def test_hitl_approve_executes_trade():
    start_run("test")
    aid = submit_for_approval(run_id="r1", proposal=_proposal(), reference_price=100.0,
                              as_of=datetime(2024, 5, 23, 10, 0).isoformat(), reasoning="ok")
    res = resolve_approval(aid, decision="approve", approver="mark")
    assert res["status"] == "APPROVED"
    assert res["fill"]["status"] == "FILLED"


def test_hitl_reject_does_not_trade():
    start_run("test")
    aid = submit_for_approval(run_id="r1", proposal=_proposal(), reference_price=100.0,
                              as_of=datetime(2024, 5, 23, 10, 0).isoformat(), reasoning="ok")
    res = resolve_approval(aid, decision="reject", approver="mark")
    assert res["status"] == "REJECTED"


def test_hitl_edit_reruns_engine_and_rejects_if_oversized():
    start_run("test")
    aid = submit_for_approval(run_id="r1", proposal=_proposal(), reference_price=100.0,
                              as_of=datetime(2024, 5, 23, 10, 0).isoformat(), reasoning="ok")
    # edit up to 1000 shares -> 100,000 notional -> engine rejects on resolve
    res = resolve_approval(aid, decision="edit", approver="mark", edited_quantity=1000)
    assert res["status"] == "REJECTED"

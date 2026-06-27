from datetime import datetime

from app.agents.schemas import ThesisCard, TradeProposal
from app.config import get_settings
from app.firm.hitl import resolve_approval, submit_for_approval
from app.guardrails import risk_engine
from app.obs.spans import start_run

S = get_settings()


def _eval(side="BUY", quantity=100, price=100.0):
    return risk_engine.evaluate(side=side, quantity=quantity, price=price, settings=S)


def test_engine_auto_approves_small_buy():
    # 100 * 100 = 10,000 < 25,000 approval threshold -> agent discretion
    assert _eval(quantity=100).decision == "AUTO_APPROVE"


def test_engine_requires_human_for_large_buy():
    # 300 * 100 = 30,000 >= 25,000 threshold -> Risk Committee
    assert _eval(quantity=300).decision == "REQUIRE_HUMAN"


def test_engine_auto_approves_sell_regardless_of_size():
    # sells are risk-reducing; the broker still refuses to oversell at fill time
    assert _eval(side="SELL", quantity=100_000).decision == "AUTO_APPROVE"


def _proposal(qty=100, notional=10_000.0):
    return TradeProposal(
        ticker="NVDA", side="BUY", quantity=qty, est_notional=notional,
        thesis_card=ThesisCard(headline="h", why_now="w", expected_edge="e", risks="r",
                               confidence=0.8),
        stop_loss_pct=0.04, take_profit_pct=0.10,
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


def test_hitl_edit_changes_quantity_and_fills():
    start_run("test")
    aid = submit_for_approval(run_id="r1", proposal=_proposal(), reference_price=100.0,
                              as_of=datetime(2024, 5, 23, 10, 0).isoformat(), reasoning="ok")
    res = resolve_approval(aid, decision="edit", approver="mark", edited_quantity=300)
    assert res["status"] == "APPROVED"
    assert res["fill"]["status"] == "FILLED"
    assert res["fill"]["quantity"] == 300

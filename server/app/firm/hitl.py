import uuid
from datetime import datetime

from app.agents.schemas import TradeProposal
from app.config import get_settings
from app.db import SessionLocal
from app.guardrails import risk_engine
from app.models.approval import ApprovalRequest
from app.models.portfolio import Trade
from app.obs.spans import span
from app.state.broker import PaperBroker
from app.state.portfolio import equity as compute_equity
from app.state.portfolio import get_or_create_portfolio, get_position


def _snapshot(session, ticker: str, price: float) -> dict:
    p = get_or_create_portfolio(session)
    session.commit()
    pos = get_position(session, p.id, ticker)
    eq = compute_equity(session, p.id, {ticker: price})
    trades_today = session.query(Trade).filter(Trade.status == "FILLED").count()
    day_pnl_pct = (eq - get_settings().starting_cash) / get_settings().starting_cash
    return {
        "cash": p.cash, "equity": eq,
        "position_qty": pos.quantity if pos else 0,
        "position_value": (pos.quantity * price) if pos else 0.0,
        "trades_today": trades_today, "day_pnl_pct": day_pnl_pct,
    }


def submit_for_approval(
    *, run_id: str, proposal: TradeProposal, reference_price: float, as_of: str, reasoning: str
) -> str:
    approval_id = uuid.uuid4().hex
    with SessionLocal() as s:
        s.add(ApprovalRequest(
            id=approval_id, run_id=run_id, ticker=proposal.ticker, side=proposal.side,
            quantity=proposal.quantity, reference_price=reference_price,
            est_notional=proposal.est_notional, as_of=as_of,
            thesis_card_json=proposal.thesis_card.model_dump(), risk_reasoning=reasoning,
            status="PENDING",
        ))
        s.commit()
    with span("HITL", "await_approval", ticker=proposal.ticker, trade_id=approval_id) as h:
        h.set(status="PENDING")
        h.set_output({"approval_id": approval_id, "side": proposal.side,
                      "quantity": proposal.quantity})
    return approval_id


def resolve_approval(
    approval_id: str, *, decision: str, approver: str, edited_quantity: int | None = None
) -> dict:
    settings = get_settings()
    with SessionLocal() as s:
        appr = s.get(ApprovalRequest, approval_id)
        if appr is None or appr.status != "PENDING":
            raise ValueError("approval not pending")

        if decision == "reject":
            appr.status = "REJECTED"
            appr.decision = "reject"
            appr.approver = approver
            appr.decided_at = datetime.utcnow()
            s.commit()
            _trace(appr, "REJECTED")
            return {"status": "REJECTED"}

        qty = edited_quantity if (decision == "edit" and edited_quantity) else appr.quantity
        snap = _snapshot(s, appr.ticker, appr.reference_price)
        result = risk_engine.evaluate(
            side=appr.side, quantity=qty, price=appr.reference_price,
            equity=snap["equity"], cash=snap["cash"], position_qty=snap["position_qty"],
            position_value=snap["position_value"], trades_today=snap["trades_today"],
            day_pnl_pct=snap["day_pnl_pct"], settings=settings,
        )
        if result.decision == "REJECT":
            appr.status = "REJECTED"
            appr.decision = decision
            appr.approver = approver
            appr.reject_reason = "; ".join(result.breaches)
            appr.decided_at = datetime.utcnow()
            s.commit()
            _trace(appr, "REJECTED")
            return {"status": "REJECTED", "breaches": result.breaches}

        appr_id, ticker, side, ref, as_of = appr.id, appr.ticker, appr.side, appr.reference_price, appr.as_of

    fill = PaperBroker().execute(
        ticker=ticker, side=side, quantity=qty, reference_price=ref,
        as_of=datetime.fromisoformat(as_of), idempotency_key=appr_id,
    )
    with SessionLocal() as s:
        appr = s.get(ApprovalRequest, approval_id)
        appr.status = "APPROVED"
        appr.decision = decision
        appr.approver = approver
        appr.edited_quantity = edited_quantity if decision == "edit" else None
        appr.trade_id = fill.trade_id
        appr.decided_at = datetime.utcnow()
        s.commit()
        _trace(appr, "APPROVED")
    return {"status": "APPROVED", "fill": fill.__dict__}


def _trace(appr: ApprovalRequest, status: str) -> None:
    with span("HITL", "decision", ticker=appr.ticker, trade_id=appr.id) as h:
        h.set(status="OK")
        h.set_output({"approval_id": appr.id, "result": status,
                      "approver": appr.approver, "decision": appr.decision})

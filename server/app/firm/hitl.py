import time
import uuid
from contextvars import ContextVar
from datetime import datetime

from app.agents.schemas import TradeProposal
from app.config import get_settings
from app.db import SessionLocal
from app.guardrails import risk_engine
from app.models.approval import ApprovalRequest
from app.obs.spans import span
from app.state.broker import PaperBroker
from app.state.portfolio import account_snapshot


class ApprovalTimeout(Exception):
    """A paused run waited past the approval timeout with no human decision."""


# Whether the run BLOCKS at a human-approval gate (true for live replays) or just
# queues the approval and continues (false for eval/CI and direct unit tests).
_blocking: ContextVar[bool] = ContextVar("hitl_blocking", default=False)


def set_blocking(value: bool) -> None:
    _blocking.set(value)


def is_blocking() -> bool:
    return _blocking.get()


def wait_for_decision(approval_id: str, timeout_seconds: float, poll_seconds: float = 0.25) -> str:
    """Block until the approval leaves PENDING (a human approved/edited/rejected via
    the API) or the timeout elapses. Returns the final status, or 'TIMEOUT'."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with SessionLocal() as s:
            appr = s.get(ApprovalRequest, approval_id)
            if appr is not None and appr.status != "PENDING":
                return appr.status
        time.sleep(poll_seconds)
    return "TIMEOUT"


def submit_for_approval(
    *, run_id: str, proposal: TradeProposal, reference_price: float, as_of: str, reasoning: str,
    severity: str | None = None,
) -> str:
    approval_id = uuid.uuid4().hex
    with SessionLocal() as s:
        s.add(ApprovalRequest(
            id=approval_id, run_id=run_id, ticker=proposal.ticker, side=proposal.side,
            quantity=proposal.quantity, reference_price=reference_price,
            est_notional=proposal.est_notional, as_of=as_of,
            thesis_card_json=proposal.thesis_card.model_dump(), risk_reasoning=reasoning,
            risk_severity=severity,
            stop_loss_pct=proposal.stop_loss_pct, take_profit_pct=proposal.take_profit_pct,
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
        snap = account_snapshot(appr.ticker, appr.reference_price, run_id=appr.run_id)
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

        appr_id, ticker, side, ref, as_of, rid = (
            appr.id, appr.ticker, appr.side, appr.reference_price, appr.as_of, appr.run_id)
        stop_loss_pct, take_profit_pct = appr.stop_loss_pct, appr.take_profit_pct

    fill = PaperBroker().execute(
        ticker=ticker, side=side, quantity=qty, reference_price=ref,
        as_of=datetime.fromisoformat(as_of), idempotency_key=appr_id, run_id=rid,
        stop_loss_pct=stop_loss_pct, take_profit_pct=take_profit_pct,
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

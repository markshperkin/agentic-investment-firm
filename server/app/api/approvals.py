from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.firm.hitl import resolve_approval
from app.models.approval import ApprovalRequest

router = APIRouter()


class DecideRequest(BaseModel):
    decision: str  # approve | edit | reject
    approver: str = "operator"
    edited_quantity: int | None = None


@router.get("/approvals")
def approvals(
    status: str = Query(default="PENDING"),
    run_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[dict]:
    stmt = select(ApprovalRequest)
    if status and status.upper() != "ALL":
        stmt = stmt.where(ApprovalRequest.status == status)
    if run_id:
        stmt = stmt.where(ApprovalRequest.run_id == run_id)
    rows = session.execute(stmt.order_by(ApprovalRequest.created_at.desc())).scalars().all()
    return [
        {
            "id": a.id, "run_id": a.run_id, "ticker": a.ticker, "side": a.side,
            "quantity": a.quantity, "est_notional": a.est_notional,
            "reference_price": a.reference_price, "as_of": a.as_of, "status": a.status,
            "thesis_card": a.thesis_card_json, "risk_reasoning": a.risk_reasoning,
            "risk_severity": a.risk_severity,
            "stop_loss_pct": a.stop_loss_pct, "take_profit_pct": a.take_profit_pct,
            "decision": a.decision, "approver": a.approver, "reject_reason": a.reject_reason,
            "edited_quantity": a.edited_quantity,
        }
        for a in rows
    ]


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: str, req: DecideRequest) -> dict:
    if req.decision not in ("approve", "edit", "reject"):
        raise HTTPException(400, "decision must be approve|edit|reject")
    try:
        return resolve_approval(
            approval_id, decision=req.decision, approver=req.approver,
            edited_quantity=req.edited_quantity,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc))

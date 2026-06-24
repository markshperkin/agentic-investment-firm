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
def approvals(status: str = Query(default="PENDING"), session: Session = Depends(get_session)) -> list[dict]:
    rows = session.execute(
        select(ApprovalRequest).where(ApprovalRequest.status == status)
        .order_by(ApprovalRequest.created_at.desc())
    ).scalars().all()
    return [
        {
            "id": a.id, "ticker": a.ticker, "side": a.side, "quantity": a.quantity,
            "est_notional": a.est_notional, "as_of": a.as_of, "status": a.status,
            "thesis_card": a.thesis_card_json, "risk_reasoning": a.risk_reasoning,
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

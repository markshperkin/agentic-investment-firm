from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.span import Run, Span

router = APIRouter()


@router.get("/runs")
def list_runs(session: Session = Depends(get_session)) -> list[dict]:
    runs = session.execute(select(Run).order_by(Run.started_at.desc())).scalars().all()
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "replay_date": r.replay_date,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
        }
        for r in runs
    ]


@router.get("/runs/{run_id}/feed")
def run_feed(
    run_id: str,
    ticker: str | None = Query(default=None),
    trade_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[dict]:
    stmt = select(Span).where(Span.run_id == run_id)
    if ticker:
        stmt = stmt.where(Span.ticker == ticker)
    if trade_id:
        stmt = stmt.where(Span.trade_id == trade_id)
    stmt = stmt.order_by(Span.started_at.asc())
    spans = session.execute(stmt).scalars().all()
    return [s.as_event() for s in spans]

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.state.portfolio import get_or_create_portfolio, open_positions

router = APIRouter()


@router.get("/portfolio")
def portfolio(session: Session = Depends(get_session)) -> dict:
    p = get_or_create_portfolio(session)
    session.commit()
    positions = open_positions(session, p.id)
    holdings = [
        {
            "ticker": pos.ticker,
            "quantity": pos.quantity,
            "avg_cost_basis": round(pos.avg_cost_basis, 4),
            "realized_pnl": round(pos.realized_pnl, 2),
        }
        for pos in positions
    ]
    cost_value = sum(pos.quantity * pos.avg_cost_basis for pos in positions)
    return {
        "cash": round(p.cash, 2),
        "currency": p.currency,
        "holdings": holdings,
        # equity at cost; mark-to-market equity is computed with live prices (T07+)
        "equity_at_cost": round(p.cash + cost_value, 2),
    }


@router.get("/positions")
def positions(session: Session = Depends(get_session)) -> list[dict]:
    p = get_or_create_portfolio(session)
    session.commit()
    return [
        {
            "ticker": pos.ticker,
            "quantity": pos.quantity,
            "avg_cost_basis": round(pos.avg_cost_basis, 4),
            "realized_pnl": round(pos.realized_pnl, 2),
        }
        for pos in open_positions(session, p.id)
    ]

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models.portfolio import Portfolio, Position, Trade


def get_or_create_portfolio(session: Session) -> Portfolio:
    portfolio = session.get(Portfolio, 1)
    if portfolio is None:
        portfolio = Portfolio(id=1, cash=get_settings().starting_cash)
        session.add(portfolio)
        session.flush()
    return portfolio


def get_position(session: Session, portfolio_id: int, ticker: str) -> Position | None:
    stmt = select(Position).where(
        Position.portfolio_id == portfolio_id, Position.ticker == ticker
    )
    return session.execute(stmt).scalar_one_or_none()


def open_positions(session: Session, portfolio_id: int) -> list[Position]:
    stmt = select(Position).where(
        Position.portfolio_id == portfolio_id, Position.quantity != 0
    )
    return list(session.execute(stmt).scalars().all())


def holdings_value(session: Session, portfolio_id: int, prices: dict[str, float]) -> float:
    return sum(p.quantity * prices.get(p.ticker, p.avg_cost_basis)
               for p in open_positions(session, portfolio_id))


def equity(session: Session, portfolio_id: int, prices: dict[str, float]) -> float:
    portfolio = session.get(Portfolio, portfolio_id)
    cash = portfolio.cash if portfolio else 0.0
    return cash + holdings_value(session, portfolio_id, prices)


def account_snapshot(ticker: str, price: float) -> dict:
    """Cash / equity / position / day-stats snapshot used by the risk engine."""
    settings = get_settings()
    with SessionLocal() as s:
        p = get_or_create_portfolio(s)
        s.commit()
        pos = get_position(s, p.id, ticker)
        eq = equity(s, p.id, {ticker: price})
        trades_today = s.query(Trade).filter(Trade.status == "FILLED").count()
        return {
            "cash": p.cash,
            "equity": eq,
            "position_qty": pos.quantity if pos else 0,
            "position_value": (pos.quantity * price) if pos else 0.0,
            "trades_today": trades_today,
            "day_pnl_pct": (eq - settings.starting_cash) / settings.starting_cash,
        }

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.portfolio import Portfolio, Position


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

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models.portfolio import Portfolio, Position, Trade
from app.models.span import Run
from app.obs.spans import current_run

# Book used outside any replay (direct unit tests / ad-hoc calls with no run bound).
DEFAULT_RUN = "default"


def _resolve_run(run_id: str | None) -> str:
    return run_id or current_run() or DEFAULT_RUN


def get_or_create_portfolio(session: Session, run_id: str | None = None) -> Portfolio:
    """The book for one run — each replay gets its own fresh $1M account. Falls back to
    the active run when run_id is not passed, or to a shared DEFAULT_RUN off-run."""
    rid = _resolve_run(run_id)
    portfolio = session.execute(
        select(Portfolio).where(Portfolio.run_id == rid)
    ).scalar_one_or_none()
    if portfolio is None:
        portfolio = Portfolio(run_id=rid, cash=get_settings().starting_cash)
        session.add(portfolio)
        session.flush()
    return portfolio


def latest_run_id(session: Session) -> str | None:
    return session.execute(
        select(Run.id).order_by(Run.started_at.desc())
    ).scalars().first()


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


def account_snapshot(ticker: str, price: float, run_id: str | None = None) -> dict:
    """Cash / equity / position / day-stats snapshot used by the risk engine, scoped
    to one run's book."""
    settings = get_settings()
    rid = _resolve_run(run_id)
    with SessionLocal() as s:
        p = get_or_create_portfolio(s, rid)
        s.commit()
        pos = get_position(s, p.id, ticker)
        eq = equity(s, p.id, {ticker: price})
        trades_today = s.query(Trade).filter(
            Trade.run_id == rid, Trade.status == "FILLED"
        ).count()
        return {
            "cash": p.cash,
            "equity": eq,
            "position_qty": pos.quantity if pos else 0,
            "position_value": (pos.quantity * price) if pos else 0.0,
            "trades_today": trades_today,
            "day_pnl_pct": (eq - settings.starting_cash) / settings.starting_cash,
        }

from sqlalchemy import select

from app.db import SessionLocal
from app.models.ticker_memory import TickerMemory


def latest(run_id: str, ticker: str) -> TickerMemory | None:
    with SessionLocal() as s:
        return s.execute(
            select(TickerMemory)
            .where(TickerMemory.run_id == run_id, TickerMemory.ticker == ticker)
            .order_by(TickerMemory.tick_seq.desc())
        ).scalars().first()


def record(
    *,
    run_id: str,
    ticker: str,
    tick_seq: int,
    as_of: str,
    stance: str | None,
    confidence: float | None,
    current_view: dict | None,
    open_thesis: str | None,
    position_qty: int,
    cost_basis: float,
    last_decision_price: float | None,
    processed_doc_ids: list | None,
    decision_log: list | None,
    dispatch_path: str | None,
) -> None:
    """One snapshot per tick (enforced by uq_memory). Across ticks the series is the
    auditable belief timeline; within a tick the row is updated in place as the tick
    resolves — e.g. a blocking HITL gate moves awaiting_approval -> approved_executed on
    the same tick, which must not insert a second row."""
    with SessionLocal() as s:
        row = s.execute(
            select(TickerMemory).where(
                TickerMemory.run_id == run_id,
                TickerMemory.ticker == ticker,
                TickerMemory.tick_seq == tick_seq,
            )
        ).scalars().first()
        if row is None:
            row = TickerMemory(run_id=run_id, ticker=ticker, tick_seq=tick_seq)
            s.add(row)
        row.as_of = as_of
        row.stance = stance
        row.confidence = confidence
        row.current_view_json = current_view
        row.open_thesis = open_thesis
        row.position_qty = position_qty
        row.cost_basis = cost_basis
        row.last_decision_price = last_decision_price
        row.processed_doc_ids_json = processed_doc_ids
        row.decision_log_json = decision_log
        row.dispatch_path = dispatch_path
        s.commit()

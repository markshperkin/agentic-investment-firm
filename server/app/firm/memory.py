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
    """Append a versioned snapshot — never overwrite. The full series is the
    auditable belief timeline; the latest row is the current memory."""
    with SessionLocal() as s:
        s.add(TickerMemory(
            run_id=run_id, ticker=ticker, tick_seq=tick_seq, as_of=as_of,
            stance=stance, confidence=confidence, current_view_json=current_view,
            open_thesis=open_thesis, position_qty=position_qty, cost_basis=cost_basis,
            last_decision_price=last_decision_price, processed_doc_ids_json=processed_doc_ids,
            decision_log_json=decision_log, dispatch_path=dispatch_path,
        ))
        s.commit()

from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.llm.pricing import PRICES
from app.models.span import Span
from app.models.ticker_memory import TickerMemory

router = APIRouter()


@router.get("/runs/{run_id}/tickers/{ticker}/memory")
def belief_timeline(run_id: str, ticker: str, session: Session = Depends(get_session)) -> list[dict]:
    """Append-only belief series for one ticker — how the firm's stance/confidence
    and decisions evolved tick by tick. The audit trail behind every position."""
    rows = session.execute(
        select(TickerMemory)
        .where(TickerMemory.run_id == run_id, TickerMemory.ticker == ticker)
        .order_by(TickerMemory.tick_seq.asc())
    ).scalars().all()
    return [{
        "tick_seq": m.tick_seq, "as_of": m.as_of, "path": m.dispatch_path,
        "stance": m.stance, "confidence": m.confidence, "thesis": m.open_thesis,
        "position_qty": m.position_qty, "last_decision_price": m.last_decision_price,
        "decision_log": m.decision_log_json or [],
        "processed_doc_ids": m.processed_doc_ids_json or [],
    } for m in rows]


@router.get("/runs/{run_id}/cost")
def cost_rollup(run_id: str, session: Session = Depends(get_session)) -> dict:
    spans = session.execute(
        select(Span).where(Span.run_id == run_id)
    ).scalars().all()
    def _bucket() -> dict:
        # input_tokens = prompt (cheaper rate), output_tokens = completion (pricier);
        # kept separate because they price differently. `tokens` is their sum.
        return {"calls": 0, "input_tokens": 0, "output_tokens": 0, "tokens": 0, "cost_usd": 0.0}

    def _add(b: dict, s: Span) -> None:
        b["calls"] += 1
        b["input_tokens"] += s.prompt_tokens
        b["output_tokens"] += s.completion_tokens
        b["tokens"] += s.prompt_tokens + s.completion_tokens
        b["cost_usd"] = round(b["cost_usd"] + s.cost_usd, 6)

    by_model: dict[str, dict] = defaultdict(_bucket)
    by_agent: dict[str, dict] = defaultdict(_bucket)
    total = _bucket()
    for s in spans:
        if not s.model:
            continue
        _add(by_model[s.model], s)
        _add(by_agent[s.agent or "unknown"], s)
        _add(total, s)

    # Per-model USD rates per 1M tokens, so the price math is transparent in the UI.
    rates = {m: {"input_per_m": pin, "output_per_m": pout} for m, (pin, pout) in PRICES.items()}
    return {"run_id": run_id, "total": total, "by_model": by_model, "by_agent": by_agent, "rates": rates}

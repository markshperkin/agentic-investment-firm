from datetime import datetime

from sqlalchemy import select

from app.config import get_settings
from app.data import price_feed
from app.db import SessionLocal
from app.models.portfolio import Portfolio, Position, Trade
from app.models.span import Run, Span
from app.models.ticker_memory import TickerMemory

BENCHMARK = "SPY"


def _eod(replay_date: str) -> datetime:
    return datetime.fromisoformat(replay_date).replace(hour=16, minute=0)


def _close_price(replay_date: str, ticker: str) -> float | None:
    try:
        return price_feed.price_at(replay_date, ticker, _eod(replay_date))
    except FileNotFoundError:
        return None


def build_report(run_id: str) -> dict:
    """Assemble the end-of-day report. Every number is read from the store
    (portfolio, trades, memory, spans) — the LLM never produces a figure."""
    settings = get_settings()
    with SessionLocal() as s:
        run = s.get(Run, run_id)
        replay_date = run.replay_date if run else None
        portfolio = s.execute(
            select(Portfolio).where(Portfolio.run_id == run_id)
        ).scalar_one_or_none()
        cash = portfolio.cash if portfolio else settings.starting_cash
        positions = list(s.execute(
            select(Position).where(Position.portfolio_id == portfolio.id, Position.quantity != 0)
        ).scalars().all()) if portfolio else []
        trades = list(s.execute(
            select(Trade).where(Trade.run_id == run_id).order_by(Trade.created_at.asc())
        ).scalars().all())
        memories = list(s.execute(
            select(TickerMemory).where(TickerMemory.run_id == run_id)
            .order_by(TickerMemory.tick_seq.asc())
        ).scalars().all())
        spans = list(s.execute(select(Span).where(Span.run_id == run_id)).scalars().all())

    holdings, holdings_value = [], 0.0
    for p in positions:
        price = _close_price(replay_date, p.ticker) if replay_date else None
        mark = price if price is not None else p.avg_cost_basis
        mv = p.quantity * mark
        holdings_value += mv
        holdings.append({
            "ticker": p.ticker, "quantity": p.quantity,
            "avg_cost_basis": round(p.avg_cost_basis, 4), "mark": round(mark, 4),
            "market_value": round(mv, 2),
            "unrealized_pnl": round((mark - p.avg_cost_basis) * p.quantity, 2),
            "realized_pnl": round(p.realized_pnl, 2),
        })

    equity = cash + holdings_value
    port_return = (equity - settings.starting_cash) / settings.starting_cash

    spy_return = None
    if replay_date:
        try:
            f = price_feed.price_features(replay_date, BENCHMARK, _eod(replay_date))
            spy_return = f["pct_change"]
        except FileNotFoundError:
            spy_return = None

    decision_log = [_decision_row(m) for m in memories]
    _annotate_actions(decision_log, trades)
    trade_log = [{
        "ticker": t.ticker, "side": t.side, "quantity": t.quantity, "status": t.status,
        "fill_price": t.fill_price, "realized_pnl": t.realized_pnl, "as_of": t.as_of,
    } for t in trades]

    return {
        "run_id": run_id,
        "replay_date": replay_date,
        "metrics": {
            "starting_cash": settings.starting_cash,
            "cash": round(cash, 2),
            "holdings_value": round(holdings_value, 2),
            "equity": round(equity, 2),
            "portfolio_return": round(port_return, 6),
            "benchmark": BENCHMARK,
            "benchmark_return": spy_return,
            "alpha": round(port_return - spy_return, 6) if spy_return is not None else None,
            "n_trades": len([t for t in trades if t.status == "FILLED"]),
        },
        "process": process_metrics(spans),
        "holdings": holdings,
        "trades": trade_log,
        "decisions": decision_log,
    }


def _annotate_actions(decision_log: list[dict], trades: list) -> None:
    """Add a running share count and a plain action to each tick row, derived from the
    FILLED trades at that tick: Bought / Sold (a fill), Skipped (the no-op SKIP path),
    or Held (a path ran but did not trade). Rows are already in chronological order."""
    fills = {(t.as_of, t.ticker): (t.side, t.quantity) for t in trades if t.status == "FILLED"}
    held: dict[str, int] = {}
    for row in decision_log:
        fill = fills.get((row["as_of"], row["ticker"]))
        if fill:
            side, qty = fill
            held[row["ticker"]] = held.get(row["ticker"], 0) + (qty if side == "BUY" else -qty)
            row["action"] = f"Bought {qty}" if side == "BUY" else f"Sold {qty}"
        elif row["path"] == "SKIP":
            row["action"] = "Skipped"
        else:
            row["action"] = "Held"
        row["shares_held"] = held.get(row["ticker"], 0)


def _decision_row(m: TickerMemory) -> dict:
    citations = []
    view = m.current_view_json or {}
    for kp in view.get("key_points", []):
        cite = kp.get("citation", {})
        citations.append({"chunk_id": cite.get("chunk_id"), "source": cite.get("source", ""),
                          "text": kp.get("text")})
    return {
        "tick_seq": m.tick_seq, "as_of": m.as_of, "ticker": m.ticker,
        "path": m.dispatch_path, "stance": m.stance, "confidence": m.confidence,
        "thesis": m.open_thesis, "decision_log": m.decision_log_json or [],
        "citations": citations,
    }


def process_metrics(spans: list) -> dict:
    """Guardrail / grounding health derived from the trace — the observability
    half of the report (groundedness, refusals, blocks, cost)."""
    cost = sum(s.cost_usd for s in spans)
    tokens = sum(s.prompt_tokens + s.completion_tokens for s in spans)
    citation_checks = [s for s in spans if s.name == "citation_check"]
    grounded = sum(1 for s in citation_checks if s.status == "OK")
    refusals = sum(1 for s in spans
                   if isinstance(s.output_json, dict)
                   and s.output_json.get("outcome") in ("insufficient_evidence", "no_actionable_view"))
    risk_rejects = sum(1 for s in spans
                       if s.name == "risk_engine" and isinstance(s.output_json, dict)
                       and s.output_json.get("decision") == "REJECT")
    injections = sum(1 for s in spans if s.name == "injection_scan")
    return {
        "total_cost_usd": round(cost, 6),
        "total_tokens": tokens,
        "citation_checks": len(citation_checks),
        "grounded_views": grounded,
        "groundedness": round(grounded / len(citation_checks), 3) if citation_checks else None,
        "refusals": refusals,
        "risk_engine_rejects": risk_rejects,
        "injection_quarantines": injections,
    }

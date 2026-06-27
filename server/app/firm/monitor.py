from datetime import datetime

from app.agents.day_review import DayReviewAgent
from app.agents.schemas import ResearchView
from app.config import get_settings
from app.data import price_feed
from app.db import SessionLocal
from app.firm import memory
from app.firm.pipeline import _chunks_for_docs, _new_documents
from app.guardrails import risk_engine
from app.llm.router import LLMRouter
from app.obs.spans import span
from app.state.broker import PaperBroker
from app.state.portfolio import account_snapshot, get_or_create_portfolio, open_positions


def stop_triggers(tickers: list[str], replay_date: str, as_of: datetime) -> list[dict]:
    """Deterministic protective-exit scan: any held position whose price has fallen
    through its stop or risen through its target. No LLM — pure price vs cost basis."""
    settings = get_settings()
    with SessionLocal() as s:
        p = get_or_create_portfolio(s)
        s.commit()
        positions = open_positions(s, p.id)
        held = [(pos.ticker, pos.quantity, pos.avg_cost_basis,
                 pos.stop_loss_pct, pos.take_profit_pct) for pos in positions]

    out: list[dict] = []
    for ticker, qty, basis, stop, target in held:
        if ticker not in tickers or qty <= 0 or basis <= 0:
            continue
        price = price_feed.price_at(replay_date, ticker, as_of)
        if price is None:
            continue
        stop = stop or settings.stop_loss_pct
        target = target or settings.take_profit_pct
        if price <= basis * (1 - stop):
            out.append({"ticker": ticker, "quantity": qty, "price": price, "kind": "STOP_LOSS"})
        elif price >= basis * (1 + target):
            out.append({"ticker": ticker, "quantity": qty, "price": price, "kind": "TAKE_PROFIT"})
    return out


def _protective_sell(*, run_id, ticker, quantity, price, as_of, tick_seq, dispatch_path, kind,
                     record: bool = True) -> dict:
    """Deterministic risk-reducing sell. Routes through the engine (a SELL within
    holdings auto-approves) then the broker. No human gate — protective by design.
    `record=False` lets the caller (day_review) write a richer memory row itself."""
    settings = get_settings()
    snap = account_snapshot(ticker, price)
    qty = min(quantity, snap["position_qty"])
    if qty <= 0:
        return {"outcome": "nothing_to_sell"}

    engine = risk_engine.evaluate(
        side="SELL", quantity=qty, price=price, equity=snap["equity"], cash=snap["cash"],
        position_qty=snap["position_qty"], position_value=snap["position_value"],
        trades_today=snap["trades_today"], day_pnl_pct=snap["day_pnl_pct"], settings=settings,
    )
    if engine.decision == "REJECT":
        if record:
            _remember(run_id, ticker, tick_seq, as_of, dispatch_path, price, qty,
                      [{"action": "protective_sell_rejected", "kind": kind, "breaches": engine.breaches}])
        return {"outcome": "rejected", "breaches": engine.breaches}

    fill = PaperBroker().execute(ticker=ticker, side="SELL", quantity=qty,
                                 reference_price=price, as_of=as_of)
    if record:
        _remember(run_id, ticker, tick_seq, as_of, dispatch_path, price, qty,
                  [{"action": "protective_sell", "kind": kind, "trade_id": fill.trade_id}])
    return {"outcome": "protective_sell", "kind": kind, "trade_id": fill.trade_id}


def process_monitor_sell(*, run_id, ticker, as_of: datetime, tick_seq, trigger: dict) -> dict:
    with span("AGENT", f"monitor:{ticker}", agent="pipeline", ticker=ticker,
              input={"path": "MONITOR_SELL", "kind": trigger.get("kind")}) as h:
        result = _protective_sell(
            run_id=run_id, ticker=ticker, quantity=trigger["quantity"], price=trigger["price"],
            as_of=as_of, tick_seq=tick_seq, dispatch_path="MONITOR_SELL", kind=trigger["kind"],
        )
        h.set_output(result)
        return result


def process_day_review(*, run_id, ticker, as_of: datetime, tick_seq, last_as_of,
                       retriever, router: LLMRouter) -> dict:
    """End-of-day framing for one ticker: delta-retrieve fresh evidence, then ask the
    PM to HOLD / TRIM / FLATTEN against overnight gap risk. Execution is deterministic."""
    replay_date = as_of.date().isoformat()
    price = price_feed.price_at(replay_date, ticker, as_of)
    snap = account_snapshot(ticker, price or 0.0)
    position_qty = snap["position_qty"]

    with span("AGENT", f"review:{ticker}", agent="pipeline", ticker=ticker,
              input={"path": "DAY_REVIEW", "position_qty": position_qty}) as h:
        if position_qty <= 0 or price is None:
            _record_review(run_id, ticker, tick_seq, as_of, price, position_qty,
                           prior_view=None, decision=None, log=[{"action": "eod_no_position"}])
            h.set_output({"outcome": "no_position"})
            return {"outcome": "no_position"}

        prev = memory.latest(run_id, ticker)
        prior_view = None
        if prev is not None and prev.current_view_json:
            try:
                prior_view = ResearchView(**prev.current_view_json)
            except Exception:  # noqa: BLE001
                prior_view = None

        delta_points = _delta_evidence(ticker, prev, last_as_of, as_of)
        features = price_feed.price_features(replay_date, ticker, as_of)
        decision = DayReviewAgent(router).decide(
            ticker=ticker, position_qty=position_qty, price_features=features,
            prior_view=prior_view, delta_points=delta_points,
        )

        settings = get_settings()
        result: dict = {"outcome": "hold"}
        if decision.action == "FLATTEN":
            result = _protective_sell(run_id=run_id, ticker=ticker, quantity=position_qty,
                                      price=price, as_of=as_of, tick_seq=tick_seq,
                                      dispatch_path="DAY_REVIEW", kind="EOD_FLATTEN", record=False)
        elif decision.action == "TRIM":
            qty = max(1, int(position_qty * settings.trim_fraction))
            result = _protective_sell(run_id=run_id, ticker=ticker, quantity=qty,
                                      price=price, as_of=as_of, tick_seq=tick_seq,
                                      dispatch_path="DAY_REVIEW", kind="EOD_TRIM", record=False)

        # one rich row for the report's decision log: the standing stance/confidence plus
        # the EOD action + reasoning as the thesis, and the trade reference if it sold.
        log = [{"action": f"eod_{decision.action.lower()}", "reasoning": decision.reasoning,
                "gap_risk": decision.gap_risk}]
        if result.get("trade_id"):
            log[0]["kind"] = result.get("kind")
            log[0]["trade_id"] = result["trade_id"]
        remaining = account_snapshot(ticker, price)["position_qty"]
        _record_review(run_id, ticker, tick_seq, as_of, price, remaining, prior_view, decision, log)

        result["eod_action"] = decision.action
        h.set_output(result)
        return result


def _delta_evidence(ticker, prev, last_as_of, as_of) -> list[str]:
    seen = set(prev.processed_doc_ids_json or []) if prev else set()
    new_docs = _new_documents(ticker, last_as_of, as_of, exclude=seen)
    if not new_docs:
        return []
    chunks = _chunks_for_docs([d.id for d in new_docs], ticker, as_of)
    return [f"[{c.form_type} {c.published_date}] {c.text[:200]}" for c in chunks[:3]]


def _remember(run_id, ticker, tick_seq, as_of, dispatch_path, price, position_qty, decision_log) -> None:
    memory.record(
        run_id=run_id, ticker=ticker, tick_seq=tick_seq, as_of=as_of.isoformat(),
        stance=None, confidence=None, current_view=None, open_thesis=None,
        position_qty=position_qty, cost_basis=0.0, last_decision_price=price,
        processed_doc_ids=[], decision_log=decision_log, dispatch_path=dispatch_path,
    )


def _record_review(run_id, ticker, tick_seq, as_of, price, position_qty, prior_view, decision, log) -> None:
    """Write the EOD review into the belief timeline so the report's decision log shows
    what day_review did: stance/confidence carried from the standing view, and the EOD
    action + reasoning as the thesis."""
    thesis = f"EOD {decision.action}: {decision.reasoning}" if decision is not None else None
    memory.record(
        run_id=run_id, ticker=ticker, tick_seq=tick_seq, as_of=as_of.isoformat(),
        stance=prior_view.stance if prior_view else None,
        confidence=prior_view.confidence if prior_view else None,
        current_view=prior_view.model_dump() if prior_view else None,
        open_thesis=thesis, position_qty=position_qty, cost_basis=0.0,
        last_decision_price=price, processed_doc_ids=[], decision_log=log,
        dispatch_path="DAY_REVIEW",
    )

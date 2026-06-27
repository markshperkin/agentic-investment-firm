from datetime import datetime

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models.approval import ApprovalRequest
from app.models.portfolio import Portfolio, Position, Trade
from app.obs.spans import span
from app.state.broker import PaperBroker


def _trade_filled(session, trade_id: str | None) -> bool:
    if not trade_id:
        return False
    t = session.get(Trade, trade_id)
    return t is not None and t.status == "FILLED"


def reconcile_unfilled_approvals() -> list[dict]:
    """An approval can be marked APPROVED while the fill that should follow it was
    lost to a crash. Re-drive each such approval through the broker using the
    approval id as the idempotency key — a fill that already happened replays as a
    no-op, so this can never double-fill."""
    fixed: list[dict] = []
    with SessionLocal() as s:
        approved = s.execute(
            select(ApprovalRequest).where(ApprovalRequest.status == "APPROVED")
        ).scalars().all()
        pending = [(a.id, a.run_id, a.ticker, a.side, a.edited_quantity or a.quantity,
                    a.reference_price, a.as_of)
                   for a in approved if not _trade_filled(s, a.trade_id)]

    for appr_id, run_id, ticker, side, qty, ref, as_of in pending:
        fill = PaperBroker().execute(
            ticker=ticker, side=side, quantity=qty, reference_price=ref,
            as_of=datetime.fromisoformat(as_of), idempotency_key=appr_id, run_id=run_id,
        )
        with SessionLocal() as s:
            appr = s.get(ApprovalRequest, appr_id)
            if appr:
                appr.trade_id = fill.trade_id
                s.commit()
        fixed.append({"approval_id": appr_id, "trade_id": fill.trade_id, "status": fill.status})
    return fixed


def verify_invariant() -> dict:
    """Per-run, rebuild cash and share counts from that run's FILLED trade ledger and
    compare to its stored book. Any drift means a book diverged from its own history."""
    settings = get_settings()
    with SessionLocal() as s:
        portfolios = s.execute(select(Portfolio)).scalars().all()
        trades = s.execute(select(Trade).where(Trade.status == "FILLED")).scalars().all()
        positions = s.execute(select(Position)).scalars().all()

    by_run = {p.run_id: p for p in portfolios}
    pos_by_run: dict[str, dict[str, int]] = {}
    for p in positions:
        run = next((pf.run_id for pf in portfolios if pf.id == p.portfolio_id), None)
        pos_by_run.setdefault(run, {})[p.ticker] = p.quantity

    worst_cash_drift = 0.0
    qty_drift: dict[str, int] = {}
    for run_id, portfolio in by_run.items():
        expected_cash = settings.starting_cash
        expected_qty: dict[str, int] = {}
        for t in (t for t in trades if t.run_id == run_id):
            notional = (t.fill_price or 0.0) * t.quantity
            commission = t.commission or 0.0
            if t.side == "BUY":
                expected_cash -= notional + commission
                expected_qty[t.ticker] = expected_qty.get(t.ticker, 0) + t.quantity
            else:
                expected_cash += notional - commission
                expected_qty[t.ticker] = expected_qty.get(t.ticker, 0) - t.quantity
        worst_cash_drift = max(worst_cash_drift, abs(portfolio.cash - expected_cash))
        stored = pos_by_run.get(run_id, {})
        for tk in set(stored) | set(expected_qty):
            if stored.get(tk, 0) != expected_qty.get(tk, 0):
                qty_drift[f"{run_id}:{tk}"] = stored.get(tk, 0) - expected_qty.get(tk, 0)

    cash_drift = round(worst_cash_drift, 2)
    ok = cash_drift < 0.01 and not qty_drift
    return {"ok": ok, "cash_drift": cash_drift, "qty_drift": qty_drift}


def reconcile_on_boot() -> dict:
    fixed = reconcile_unfilled_approvals()
    invariant = verify_invariant()
    # Only leave a trace when there was something to fix or the book is off — a
    # clean boot stays silent.
    if fixed or not invariant["ok"]:
        with span("EVENT", "crash_recovery", input={"reconciled": len(fixed)}) as h:
            h.set(status="OK" if invariant["ok"] else "ERROR")
            h.set_output({"reconciled": fixed, "invariant": invariant})
    return {"reconciled": fixed, "invariant": invariant}

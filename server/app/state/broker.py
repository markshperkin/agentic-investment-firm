import uuid
from dataclasses import dataclass
from datetime import datetime

from app.config import get_settings
from app.db import SessionLocal
from app.models.portfolio import Position, Trade
from app.obs.spans import span
from app.obs.spans import current_run
from app.state.market_hours import is_market_open
from app.state.portfolio import get_or_create_portfolio, get_position


@dataclass
class Fill:
    trade_id: str
    status: str
    ticker: str
    side: str
    quantity: int
    fill_price: float | None = None
    slippage: float | None = None
    commission: float | None = None
    realized_pnl: float | None = None
    reason: str | None = None


class PaperBroker:
    """Deterministic simulated execution. Applies slippage + commission, enforces
    market hours and the no-oversell rule, and writes the fill in a single
    transaction so the book is never left half-updated."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def _fill_price(self, side: str, reference_price: float) -> tuple[float, float]:
        slip = reference_price * self.settings.slippage_bps / 10_000
        if side == "BUY":
            return reference_price + slip, slip
        return reference_price - slip, slip

    def execute(
        self,
        *,
        ticker: str,
        side: str,
        quantity: int,
        reference_price: float,
        as_of: datetime,
        idempotency_key: str | None = None,
        run_id: str | None = None,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
    ) -> Fill:
        key = idempotency_key or uuid.uuid4().hex
        rid = run_id or current_run()
        with span("EXECUTION", f"execute:{side}:{ticker}", ticker=ticker,
                  input={"side": side, "quantity": quantity, "reference_price": reference_price}) as h:
            with SessionLocal() as s:
                existing = s.query(Trade).filter_by(idempotency_key=key).one_or_none()
                if existing:
                    h.set(status="OK")
                    return self._fill_from_trade(existing, reason="idempotent_replay")

                trade = Trade(
                    id=uuid.uuid4().hex, run_id=rid, ticker=ticker, side=side, quantity=quantity,
                    reference_price=reference_price, idempotency_key=key,
                    as_of=as_of.isoformat(), status="PENDING",
                )

                if not is_market_open(as_of):
                    trade.status = "REJECTED_MARKET_CLOSED"
                    s.add(trade)
                    s.commit()
                    h.set(status="REJECTED")
                    fill = self._fill_from_trade(trade, reason="market_closed")
                    h.set_output(fill.__dict__)
                    return fill

                portfolio = get_or_create_portfolio(s, rid)
                position = get_position(s, portfolio.id, ticker)
                fill_price, slip = self._fill_price(side, reference_price)
                commission = self.settings.commission_per_trade

                if side == "SELL" and (position is None or position.quantity < quantity):
                    trade.status = "REJECTED_LIMIT"
                    s.add(trade)
                    s.commit()
                    h.set(status="REJECTED")
                    fill = self._fill_from_trade(trade, reason="oversell")
                    h.set_output(fill.__dict__)
                    return fill

                realized = None
                if side == "BUY":
                    cost = fill_price * quantity + commission
                    if cost > portfolio.cash:
                        trade.status = "REJECTED_LIMIT"
                        s.add(trade)
                        s.commit()
                        h.set(status="REJECTED")
                        fill = self._fill_from_trade(trade, reason="insufficient_cash")
                        h.set_output(fill.__dict__)
                        return fill
                    portfolio.cash -= cost
                    if position is None:
                        position = Position(portfolio_id=portfolio.id, ticker=ticker,
                                            quantity=0, avg_cost_basis=0.0)
                        s.add(position)
                    new_qty = position.quantity + quantity
                    position.avg_cost_basis = (
                        position.quantity * position.avg_cost_basis + quantity * fill_price
                    ) / new_qty
                    position.quantity = new_qty
                    if stop_loss_pct is not None:
                        position.stop_loss_pct = stop_loss_pct
                    if take_profit_pct is not None:
                        position.take_profit_pct = take_profit_pct
                else:  # SELL
                    proceeds = fill_price * quantity - commission
                    realized = (fill_price - position.avg_cost_basis) * quantity - commission
                    portfolio.cash += proceeds
                    position.realized_pnl += realized
                    position.quantity -= quantity
                    if position.quantity == 0:
                        position.avg_cost_basis = 0.0

                trade.status = "FILLED"
                trade.fill_price = fill_price
                trade.slippage = slip
                trade.commission = commission
                trade.realized_pnl = realized
                trade.filled_at = datetime.utcnow()
                s.add(trade)
                s.commit()

                h.set(status="OK")
                fill = self._fill_from_trade(trade)
                h.set_output(fill.__dict__)
                return fill

    @staticmethod
    def _fill_from_trade(trade: Trade, reason: str | None = None) -> Fill:
        return Fill(
            trade_id=trade.id, status=trade.status, ticker=trade.ticker, side=trade.side,
            quantity=trade.quantity, fill_price=trade.fill_price, slippage=trade.slippage,
            commission=trade.commission, realized_pnl=trade.realized_pnl, reason=reason,
        )

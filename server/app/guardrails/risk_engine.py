from dataclasses import dataclass, field

from app.config import Settings


@dataclass
class RiskEngineResult:
    decision: str  # REJECT | REQUIRE_HUMAN | AUTO_APPROVE
    breaches: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


def evaluate(
    *,
    side: str,
    quantity: int,
    price: float,
    equity: float,
    cash: float,
    position_qty: int,
    position_value: float,
    trades_today: int,
    day_pnl_pct: float,
    settings: Settings,
) -> RiskEngineResult:
    """Deterministic gate to the book. Hard breaches -> REJECT (no agent can
    override). Every legal BUY -> REQUIRE_HUMAN. Risk-reducing SELL -> AUTO_APPROVE."""
    notional = quantity * price
    breaches: list[str] = []

    if side == "BUY":
        if notional > settings.max_order_notional:
            breaches.append(f"order notional {notional:.0f} > cap {settings.max_order_notional:.0f}")
        if position_value + notional > settings.max_position_pct * equity:
            breaches.append(f"position would exceed {settings.max_position_pct:.0%} of equity")
        if notional > cash:
            breaches.append("insufficient cash")
        if trades_today >= settings.max_trades_per_day:
            breaches.append("max trades/day reached")
        if day_pnl_pct <= -settings.max_daily_loss_pct:
            breaches.append("daily-loss kill-switch engaged")
    else:  # SELL
        if quantity > position_qty:
            breaches.append("oversell (no shorting beyond holdings)")

    detail = {"notional": round(notional, 2), "day_pnl_pct": day_pnl_pct}
    if breaches:
        return RiskEngineResult("REJECT", breaches, detail)
    if side == "BUY":
        return RiskEngineResult("REQUIRE_HUMAN", [], detail)
    return RiskEngineResult("AUTO_APPROVE", [], detail)

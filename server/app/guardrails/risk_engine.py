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
    settings: Settings,
    equity: float = 0.0,
    cash: float = 0.0,
    position_qty: int = 0,
    position_value: float = 0.0,
    trades_today: int = 0,
    day_pnl_pct: float = 0.0,
) -> RiskEngineResult:
    """Two-tier gate to the book:

      * SELL — risk-reducing, always AUTO_APPROVE (the broker still refuses to
        oversell at fill time, so a sell beyond holdings simply doesn't fill).
      * BUY  — AUTO_APPROVE below the approval threshold; at/above it the trade
        escalates to the human Risk Committee (REQUIRE_HUMAN), which pauses the run.

    There are no policy REJECTs — impossible fills (insufficient cash, oversell) are
    caught physically by the paper broker, not by a rule here."""
    notional = round(quantity * price, 2)
    detail = {"notional": notional, "threshold": settings.approval_notional_threshold}

    if side == "SELL":
        return RiskEngineResult("AUTO_APPROVE", [], detail)
    if notional >= settings.approval_notional_threshold:
        return RiskEngineResult("REQUIRE_HUMAN", [], detail)
    return RiskEngineResult("AUTO_APPROVE", [], detail)

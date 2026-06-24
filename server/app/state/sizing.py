def position_sizer(
    *,
    confidence: float,
    equity: float,
    price: float,
    cash: float,
    max_position_pct: float,
    max_order_notional: float,
) -> int:
    """Confidence-scaled fraction of equity, clamped by the per-order notional cap
    and available cash. Deterministic — the LLM never picks the size."""
    if price <= 0:
        return 0
    target_notional = min(equity * max_position_pct * confidence, max_order_notional, cash)
    return max(int(target_notional // price), 0)

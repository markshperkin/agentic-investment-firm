def position_sizer(
    *,
    confidence: float,
    equity: float,
    price: float,
    cash: float,
    max_position_pct: float,
) -> int:
    """Confidence-scaled fraction of equity, clamped only by available cash.
    Deterministic — the LLM never picks the size. Orders may exceed the human-
    approval threshold; that escalation is the risk engine's job, not the sizer's."""
    if price <= 0:
        return 0
    target_notional = min(equity * max_position_pct * confidence, cash)
    return max(int(target_notional // price), 0)

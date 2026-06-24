from dataclasses import dataclass


@dataclass
class DispatchDecision:
    path: str
    reason: str


def decide(
    *,
    tick_index: int,
    n_ticks: int,
    max_abs_move: float,
    threshold: float,
    has_new_docs: bool = False,
    has_stop_trigger: bool = False,
) -> DispatchDecision:
    """Deterministic, first-match-wins routing. Same inputs -> same path, every run."""
    if tick_index == 0:
        return DispatchDecision("CONTEXT_BUILD", "market open")
    if tick_index == n_ticks - 1:
        return DispatchDecision("DAY_REVIEW", "pre-close review")
    if has_new_docs:
        return DispatchDecision("INCREMENTAL_NEWS", "new filing since last tick")
    if max_abs_move >= threshold:
        return DispatchDecision("PRICE_REEVAL", f"price moved >= {threshold:.0%}")
    if has_stop_trigger:
        return DispatchDecision("MONITOR_SELL", "stop/target triggered")
    return DispatchDecision("SKIP", f"no new evidence, max move {max_abs_move:.1%}")

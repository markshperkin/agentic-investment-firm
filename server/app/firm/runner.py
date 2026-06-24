from app.config import get_settings
from app.data import price_feed
from app.firm import clock
from app.firm.dispatcher import decide
from app.obs.spans import end_run, set_tick, span, start_run


def _max_abs_move(replay_date: str, tickers: list[str], as_of) -> float:
    moves: list[float] = []
    for t in tickers:
        try:
            f = price_feed.price_features(replay_date, t, as_of)
        except FileNotFoundError:
            continue
        if f["pct_change"] is not None:
            moves.append(abs(f["pct_change"]))
    return max(moves) if moves else 0.0


def run_replay(replay_date: str, tickers: list[str]) -> str:
    settings = get_settings()
    run_id = start_run(kind="replay", replay_date=replay_date)
    times = clock.ticks(replay_date, settings.tick_interval_minutes)

    for i, as_of in enumerate(times):
        set_tick(i, as_of.isoformat())
        move = _max_abs_move(replay_date, tickers, as_of)
        decision = decide(
            tick_index=i,
            n_ticks=len(times),
            max_abs_move=move,
            threshold=settings.price_move_threshold,
        )
        with span("TICK", decision.path, input={"reason": decision.reason, "max_abs_move": move}) as h:
            h.set_output({"path": decision.path, "reason": decision.reason})
            # Path handlers (CONTEXT_BUILD / INCREMENTAL_NEWS / ... ) are wired in T14.
            # The skeleton records the decision so the day visibly steps in the feed.

    end_run(run_id)
    return run_id

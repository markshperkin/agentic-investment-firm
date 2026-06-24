from app.config import get_settings
from app.data import price_feed
from app.firm import clock
from app.firm.dispatcher import decide
from app.firm.pipeline import process_ticker
from app.llm.router import LLMRouter
from app.obs.spans import end_run, set_tick, span, start_run
from app.rag.retriever import Retriever


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


def run_replay(
    replay_date: str,
    tickers: list[str],
    retriever: Retriever | None = None,
    router: LLMRouter | None = None,
) -> str:
    settings = get_settings()
    if retriever is None or router is None:
        from app.llm.factory import get_router
        from app.rag.factory import get_retriever

        retriever = retriever or get_retriever()
        router = router or get_router()

    run_id = start_run(kind="replay", replay_date=replay_date)
    times = clock.ticks(replay_date, settings.tick_interval_minutes)

    for i, as_of in enumerate(times):
        set_tick(i, as_of.isoformat())
        move = _max_abs_move(replay_date, tickers, as_of)
        decision = decide(tick_index=i, n_ticks=len(times), max_abs_move=move,
                          threshold=settings.price_move_threshold)
        with span("TICK", decision.path, input={"reason": decision.reason, "max_abs_move": move}) as h:
            h.set_output({"path": decision.path, "reason": decision.reason})
            if decision.path == "CONTEXT_BUILD":
                for ticker in tickers:
                    _safe_process(run_id, ticker, as_of, i, decision.path, retriever, router)
            # INCREMENTAL_NEWS / PRICE_REEVAL / DAY_REVIEW / MONITOR_SELL wired in T17–T18.

    end_run(run_id)
    return run_id


def _safe_process(run_id, ticker, as_of, tick_seq, path, retriever, router) -> None:
    """Partial-failure isolation: one ticker's pipeline error degrades to an error
    span and the run continues, rather than crashing the firm."""
    try:
        process_ticker(run_id=run_id, ticker=ticker, as_of=as_of, tick_seq=tick_seq,
                       dispatch_path=path, retriever=retriever, router=router)
    except Exception as exc:  # noqa: BLE001
        with span("EVENT", "NODE_ERROR", ticker=ticker,
                  input={"error": f"{type(exc).__name__}: {exc}"}) as h:
            h.set(status="ERROR")

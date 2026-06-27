from datetime import datetime

from sqlalchemy import select

from app.config import get_settings
from app.data import price_feed
from app.db import SessionLocal
from app.firm import clock
from app.firm.dispatcher import decide
from app.firm.pipeline import (
    process_incremental_news,
    process_price_reeval,
    process_ticker,
)
from app.llm.router import LLMRouter
from app.models.corpus import Document
from app.obs.spans import end_run, set_tick, span, start_run
from app.rag.retriever import Retriever


def _max_abs_move(replay_date: str, tickers: list[str], as_of, prev_as_of) -> float:
    return max((_pct(replay_date, t, as_of, prev_as_of) for t in tickers), default=0.0)


def _pct(replay_date: str, ticker: str, as_of, prev_as_of) -> float:
    """Absolute tick-over-tick move for `ticker`: |Δ since the previous tick|."""
    try:
        m = price_feed.move_since(replay_date, ticker, prev_as_of, as_of)
    except FileNotFoundError:
        return 0.0
    return abs(m) if m is not None else 0.0


def _tickers_with_move(replay_date, tickers, as_of, prev_as_of, threshold) -> list[str]:
    return [t for t in tickers if _pct(replay_date, t, as_of, prev_as_of) >= threshold]


def _tickers_with_new_docs(tickers, last_as_of: datetime | None, as_of: datetime) -> list[str]:
    if last_as_of is None:
        return []
    lo, hi = last_as_of.timestamp(), as_of.timestamp()
    with SessionLocal() as s:
        rows = s.execute(
            select(Document.ticker).where(
                Document.ticker.in_(tickers),
                Document.published_ts > lo,
                Document.published_ts <= hi,
            )
        ).scalars().all()
    return sorted(set(rows))


def run_replay(
    replay_date: str,
    tickers: list[str],
    retriever: Retriever | None = None,
    router: LLMRouter | None = None,
    *,
    block_on_approval: bool = True,
    run_id: str | None = None,
) -> str:
    settings = get_settings()
    # The benchmark (SPY) is scored against, never traded — keep it out of the
    # research/trade universe even if a caller (or the UI) passes it in.
    from app.data.prices import BENCHMARK
    from app.firm import hitl

    tickers = [t for t in tickers if t != BENCHMARK]
    # Live replays pause at a human-approval gate; eval/CI pass False to queue-and-continue.
    hitl.set_blocking(block_on_approval)
    if retriever is None or router is None:
        from app.llm.factory import get_router
        from app.rag.factory import get_retriever

        retriever = retriever or get_retriever()
        router = router or get_router()

    from app.firm.hitl import ApprovalTimeout
    from app.guardrails import budget
    from app.guardrails.budget import Budget, BudgetExceeded
    from app.obs.spans import set_run

    if run_id is None:
        run_id = start_run(kind="replay", replay_date=replay_date)
    else:
        set_run(run_id)  # continue a run_id created by the request handler (background run)
    budget.start(Budget(max_calls=settings.max_llm_calls_per_run,
                        max_tokens=settings.max_tokens_per_run,
                        max_seconds=settings.max_run_seconds))
    times = clock.ticks(replay_date, settings.tick_interval_minutes)

    try:
        _run_ticks(run_id, replay_date, tickers, times, settings, retriever, router)
    except BudgetExceeded as exc:
        with span("EVENT", "BUDGET_EXCEEDED", input={"reason": str(exc)}) as h:
            h.set(status="ERROR")
        end_run(run_id, status="HALTED")
        budget.clear()
        return run_id
    except ApprovalTimeout as exc:
        with span("EVENT", "APPROVAL_TIMEOUT", input={"approval_id": str(exc)}) as h:
            h.set(status="ERROR")
        end_run(run_id, status="HALTED")
        budget.clear()
        return run_id

    _end_of_day_report(replay_date, times, router)
    budget.clear()
    end_run(run_id)
    return run_id


def _end_of_day_report(replay_date: str, times, router: LLMRouter) -> None:
    """Concluding step of the run: generate the end-of-day report narrative inside the run
    context so it lands in the feed (Steps) and the cost rollup — not lazily in the API
    request. Reporting failures never fail the run (narrate falls back deterministically)."""
    from app.agents.reporting import ReportingAgent
    from app.obs.spans import current_run
    from app.reports.builder import build_report

    run_id = current_run()
    if run_id is None:
        return
    set_tick(len(times), (times[-1].isoformat() if times else replay_date))
    try:
        with span("TICK", "REPORT", input={"phase": "end_of_day"}) as h:
            report = build_report(run_id)
            summary = ReportingAgent(router).narrate(report)
            h.set_output({"headline": summary.headline})
    except Exception as exc:  # noqa: BLE001
        with span("EVENT", "REPORT_ERROR", input={"error": f"{type(exc).__name__}: {exc}"}) as h:
            h.set(status="ERROR")


def _run_ticks(run_id, replay_date, tickers, times, settings, retriever, router) -> None:
    from app.firm.monitor import stop_triggers

    last_as_of: datetime | None = None
    for i, as_of in enumerate(times):
        set_tick(i, as_of.isoformat())
        move = _max_abs_move(replay_date, tickers, as_of, last_as_of)
        new_doc_tickers = _tickers_with_new_docs(tickers, last_as_of, as_of)
        triggers = stop_triggers(tickers, replay_date, as_of)
        decision = decide(
            tick_index=i, n_ticks=len(times), max_abs_move=move,
            threshold=settings.price_move_threshold,
            has_new_docs=bool(new_doc_tickers),
            has_stop_trigger=bool(triggers),
        )
        with span("TICK", decision.path, input={"reason": decision.reason, "max_abs_move": move}) as h:
            h.set_output({"path": decision.path, "reason": decision.reason})
            _dispatch(run_id, decision.path, tickers, new_doc_tickers, move_tickers=None,
                      triggers=triggers, replay_date=replay_date, as_of=as_of, last_as_of=last_as_of,
                      tick_seq=i, retriever=retriever, router=router, settings=settings)
        last_as_of = as_of


def _dispatch(run_id, path, tickers, new_doc_tickers, move_tickers, triggers, replay_date,
              as_of, last_as_of, tick_seq, retriever, router, settings) -> None:
    if path == "CONTEXT_BUILD":
        for t in tickers:
            _safe(run_id, path, t, as_of, tick_seq, retriever, router,
                  last_as_of=last_as_of)
    elif path == "INCREMENTAL_NEWS":
        for t in new_doc_tickers:
            _safe(run_id, path, t, as_of, tick_seq, retriever, router, last_as_of=last_as_of)
    elif path == "PRICE_REEVAL":
        for t in _tickers_with_move(replay_date, tickers, as_of, last_as_of, settings.price_move_threshold):
            _safe(run_id, path, t, as_of, tick_seq, retriever, router, last_as_of=last_as_of)
    elif path == "DAY_REVIEW":
        for t in tickers:
            _safe(run_id, path, t, as_of, tick_seq, retriever, router, last_as_of=last_as_of)
    elif path == "MONITOR_SELL":
        for trig in triggers:
            _safe(run_id, path, trig["ticker"], as_of, tick_seq, retriever, router,
                  last_as_of=last_as_of, trigger=trig)


def _safe(run_id, path, ticker, as_of, tick_seq, retriever, router, *, last_as_of=None, trigger=None) -> None:
    """Partial-failure isolation: one ticker's pipeline error degrades to an error
    span and the run continues. A budget breach is NOT isolated — it halts the run."""
    from app.firm.hitl import ApprovalTimeout
    from app.firm.monitor import process_day_review, process_monitor_sell
    from app.guardrails.budget import BudgetExceeded

    try:
        if path == "CONTEXT_BUILD":
            process_ticker(run_id=run_id, ticker=ticker, as_of=as_of, tick_seq=tick_seq,
                           dispatch_path=path, retriever=retriever, router=router)
        elif path == "INCREMENTAL_NEWS":
            process_incremental_news(run_id=run_id, ticker=ticker, as_of=as_of,
                                     tick_seq=tick_seq, last_as_of=last_as_of, router=router)
        elif path == "PRICE_REEVAL":
            process_price_reeval(run_id=run_id, ticker=ticker, as_of=as_of,
                                 tick_seq=tick_seq, router=router)
        elif path == "DAY_REVIEW":
            process_day_review(run_id=run_id, ticker=ticker, as_of=as_of, tick_seq=tick_seq,
                               last_as_of=last_as_of, retriever=retriever, router=router)
        elif path == "MONITOR_SELL":
            process_monitor_sell(run_id=run_id, ticker=ticker, as_of=as_of,
                                 tick_seq=tick_seq, trigger=trigger)
    except (BudgetExceeded, ApprovalTimeout):
        raise  # not isolated — these halt the whole run
    except Exception as exc:  # noqa: BLE001
        with span("EVENT", "NODE_ERROR", ticker=ticker,
                  input={"error": f"{type(exc).__name__}: {exc}"}) as h:
            h.set(status="ERROR")

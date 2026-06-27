import time
from datetime import datetime

from sqlalchemy import select

from app.agents.pm import PMAgent
from app.agents.research import ResearchAgent
from app.agents.risk import RiskAgent
from app.agents.schemas import NoTrade, ResearchView, TradeProposal
from app.config import get_settings
from app.data import price_feed
from app.db import SessionLocal
from app.firm import hitl, memory
from app.firm.hitl import submit_for_approval
from app.guardrails import budget, risk_engine
from app.guardrails.injection import scan
from app.guardrails.lookahead import assert_no_lookahead
from app.llm.router import LLMRouter
from app.models.corpus import Chunk, Document
from app.obs.spans import span
from app.rag.crag import run_crag
from app.rag.retriever import RetrievedChunk, Retriever
from app.state.broker import PaperBroker
from app.state.portfolio import account_snapshot


def _doc_ids_of(chunks: list[RetrievedChunk]) -> list[str]:
    return sorted({c.chunk_id.rsplit(":", 1)[0] for c in chunks})


def _make_remember(run_id, ticker, tick_seq, as_of, dispatch_path, price):
    def _remember(stance, confidence, thesis, view, decision_log, doc_ids=None):
        snap = account_snapshot(ticker, price or 0.0)
        memory.record(
            run_id=run_id, ticker=ticker, tick_seq=tick_seq, as_of=as_of.isoformat(),
            stance=stance, confidence=confidence, current_view=view, open_thesis=thesis,
            position_qty=snap["position_qty"], cost_basis=0.0,
            last_decision_price=price, processed_doc_ids=doc_ids or [], decision_log=decision_log,
            dispatch_path=dispatch_path,
        )
    return _remember


def process_ticker(
    *,
    run_id: str,
    ticker: str,
    as_of: datetime,
    tick_seq: int,
    dispatch_path: str,
    retriever: Retriever,
    router: LLMRouter,
    intent: str = "RESEARCH_ENTRY",
) -> dict:
    price = price_feed.price_at(as_of.date().isoformat(), ticker, as_of)
    remember = _make_remember(run_id, ticker, tick_seq, as_of, dispatch_path, price)

    with span("AGENT", f"pipeline:{ticker}", agent="pipeline", ticker=ticker,
              input={"path": dispatch_path, "as_of": as_of.isoformat()}) as h:
        if price is None:
            remember("INSUFFICIENT_EVIDENCE", 0.0, "no price", None, [{"action": "skip_no_price"}])
            h.set_output({"outcome": "no_price"})
            return {"outcome": "no_price"}

        crag = run_crag(ticker=ticker, as_of=as_of, intent=intent, retriever=retriever, router=router)
        if crag.status != "OK":
            remember("INSUFFICIENT_EVIDENCE", 0.0, "insufficient evidence", None,
                     [{"action": "refuse", "reason": "insufficient_evidence"}])
            h.set_output({"outcome": "insufficient_evidence"})
            return {"outcome": "insufficient_evidence"}

        doc_ids = _doc_ids_of(crag.chunks)
        features = price_feed.price_features(as_of.date().isoformat(), ticker, as_of)
        view = ResearchAgent(router).analyze(ticker, as_of, crag.chunks, price_features=features)
        if view.stance in ("INSUFFICIENT_EVIDENCE", "NEUTRAL"):
            remember(view.stance, view.confidence, "no actionable view", view.model_dump(),
                     [{"action": "no_trade", "reason": view.stance}], doc_ids)
            h.set_output({"outcome": "no_actionable_view", "stance": view.stance})
            return {"outcome": "no_actionable_view"}

        return _pm_risk_route(run_id, view, price, as_of, dispatch_path, tick_seq,
                              router, h, remember, doc_ids)


def process_incremental_news(
    *,
    run_id: str,
    ticker: str,
    as_of: datetime,
    tick_seq: int,
    last_as_of: datetime | None,
    router: LLMRouter,
) -> dict:
    """A filing landed since the last tick: push its chunks straight to Research
    (skip the CRAG retrieval loop). Already-seen docs are deduped via the
    processed_doc_ids carried on TickerMemory."""
    price = price_feed.price_at(as_of.date().isoformat(), ticker, as_of)
    remember = _make_remember(run_id, ticker, tick_seq, as_of, "INCREMENTAL_NEWS", price)

    prev = memory.latest(run_id, ticker)
    seen = set(prev.processed_doc_ids_json or []) if prev else set()
    new_docs = _new_documents(ticker, last_as_of, as_of, exclude=seen)

    with span("AGENT", f"news:{ticker}", agent="pipeline", ticker=ticker,
              input={"path": "INCREMENTAL_NEWS", "as_of": as_of.isoformat(),
                     "new_doc_ids": [d.id for d in new_docs]}) as h:
        if not new_docs:
            h.set_output({"outcome": "no_new_docs"})
            return {"outcome": "no_new_docs"}
        if price is None:
            remember("INSUFFICIENT_EVIDENCE", 0.0, "no price", None, [{"action": "skip_no_price"}],
                     sorted(seen))
            h.set_output({"outcome": "no_price"})
            return {"outcome": "no_price"}

        chunks = _chunks_for_docs([d.id for d in new_docs], ticker, as_of)
        doc_ids = sorted(seen | {d.id for d in new_docs})
        prior_view = None
        if prev is not None and prev.current_view_json:
            try:
                prior_view = ResearchView(**prev.current_view_json)
            except Exception:  # noqa: BLE001
                prior_view = None
        features = price_feed.price_features(as_of.date().isoformat(), ticker, as_of)
        view = ResearchAgent(router).analyze(ticker, as_of, chunks,
                                             price_features=features, prior_view=prior_view)
        if view.stance in ("INSUFFICIENT_EVIDENCE", "NEUTRAL"):
            remember(view.stance, view.confidence, "no actionable view", view.model_dump(),
                     [{"action": "no_trade", "reason": view.stance}], doc_ids)
            h.set_output({"outcome": "no_actionable_view", "stance": view.stance})
            return {"outcome": "no_actionable_view"}

        return _pm_risk_route(run_id, view, price, as_of, "INCREMENTAL_NEWS", tick_seq,
                              router, h, remember, doc_ids)


def process_price_reeval(
    *,
    run_id: str,
    ticker: str,
    as_of: datetime,
    tick_seq: int,
    router: LLMRouter,
) -> dict:
    """A material price move with no new evidence: reuse the latest cached research
    view and re-run PM against the new price. No retrieval, no re-research."""
    price = price_feed.price_at(as_of.date().isoformat(), ticker, as_of)
    remember = _make_remember(run_id, ticker, tick_seq, as_of, "PRICE_REEVAL", price)

    prev = memory.latest(run_id, ticker)
    with span("AGENT", f"reeval:{ticker}", agent="pipeline", ticker=ticker,
              input={"path": "PRICE_REEVAL", "as_of": as_of.isoformat()}) as h:
        if price is None:
            h.set_output({"outcome": "no_price"})
            return {"outcome": "no_price"}
        if prev is None or not prev.current_view_json:
            h.set_output({"outcome": "no_cached_view"})
            return {"outcome": "no_cached_view"}

        view = ResearchView(**prev.current_view_json)
        doc_ids = prev.processed_doc_ids_json or []
        if view.stance in ("INSUFFICIENT_EVIDENCE", "NEUTRAL"):
            remember(view.stance, view.confidence, "no actionable view", view.model_dump(),
                     [{"action": "no_trade", "reason": view.stance}], doc_ids)
            h.set_output({"outcome": "no_actionable_view", "stance": view.stance})
            return {"outcome": "no_actionable_view"}

        return _pm_risk_route(run_id, view, price, as_of, "PRICE_REEVAL", tick_seq,
                              router, h, remember, doc_ids)


def _pm_risk_route(run_id, view, price, as_of, dispatch_path, tick_seq, router, h, remember, doc_ids) -> dict:
    snap = account_snapshot(view.ticker, price)
    decision = PMAgent(router).decide(view, equity=snap["equity"], cash=snap["cash"], price=price,
                                      position_qty=snap["position_qty"])
    if isinstance(decision, NoTrade):
        remember(view.stance, view.confidence, "PM no-trade", view.model_dump(),
                 [{"action": "no_trade", "reason": decision.reason}], doc_ids)
        h.set_output({"outcome": "no_trade", "reason": decision.reason})
        return {"outcome": "no_trade"}
    return _risk_and_route(run_id, decision, view, price, as_of, dispatch_path,
                           tick_seq, router, h, remember, doc_ids)


def _risk_and_route(run_id, proposal: TradeProposal, view, price, as_of, dispatch_path,
                    tick_seq, router, h, remember, doc_ids) -> dict:
    settings = get_settings()
    snap = account_snapshot(proposal.ticker, price)
    engine = risk_engine.evaluate(
        side=proposal.side, quantity=proposal.quantity, price=price,
        equity=snap["equity"], cash=snap["cash"], position_qty=snap["position_qty"],
        position_value=snap["position_value"], trades_today=snap["trades_today"],
        day_pnl_pct=snap["day_pnl_pct"], settings=settings,
    )

    with span("GUARDRAIL", "risk_engine", ticker=proposal.ticker,
              input={"side": proposal.side, "quantity": proposal.quantity}) as g:
        g.set(status="REJECTED" if engine.decision == "REJECT" else "OK")
        g.set_output({"decision": engine.decision, "breaches": engine.breaches})

    thesis = proposal.thesis_card.headline
    if engine.decision == "REJECT":
        remember(view.stance, view.confidence, thesis, view.model_dump(),
                 [{"action": "rejected", "breaches": engine.breaches}], doc_ids)
        h.set_output({"outcome": "rejected", "breaches": engine.breaches})
        return {"outcome": "rejected", "breaches": engine.breaches}

    if engine.decision == "AUTO_APPROVE":
        fill = PaperBroker().execute(ticker=proposal.ticker, side=proposal.side,
                                     quantity=proposal.quantity, reference_price=price, as_of=as_of,
                                     stop_loss_pct=proposal.stop_loss_pct,
                                     take_profit_pct=proposal.take_profit_pct)
        remember(view.stance, view.confidence, thesis, view.model_dump(),
                 [{"action": "auto_executed", "trade_id": fill.trade_id}], doc_ids)
        h.set_output({"outcome": "auto_executed", "trade_id": fill.trade_id})
        return {"outcome": "auto_executed", "trade_id": fill.trade_id}

    # REQUIRE_HUMAN
    narrative = RiskAgent(router).narrate(proposal, engine)
    approval_id = submit_for_approval(run_id=run_id, proposal=proposal, reference_price=price,
                                      as_of=as_of.isoformat(), reasoning=narrative.reasoning,
                                      severity=narrative.severity)
    remember(view.stance, view.confidence, thesis, view.model_dump(),
             [{"action": "awaiting_approval", "approval_id": approval_id}], doc_ids)

    if not hitl.is_blocking():
        # Async mode (eval/CI/unit): queue the approval and continue.
        h.set_output({"outcome": "awaiting_approval", "approval_id": approval_id})
        return {"outcome": "awaiting_approval", "approval_id": approval_id}

    # Blocking mode (live replay): the run PAUSES here — nothing else moves until the
    # Risk Committee approves/edits/rejects via the API (which fills) or it times out.
    with span("HITL", "paused", ticker=proposal.ticker, trade_id=approval_id) as ph:
        ph.set(status="PENDING")
        t0 = time.monotonic()
        status = hitl.wait_for_decision(approval_id, settings.approval_timeout_seconds)
        budget.credit_wait(time.monotonic() - t0)
        ph.set(status="OK" if status in ("APPROVED", "REJECTED") else "ERROR")
        ph.set_output({"final_status": status, "approval_id": approval_id})

    if status == "TIMEOUT":
        raise hitl.ApprovalTimeout(approval_id)

    outcome = "approved_executed" if status == "APPROVED" else "rejected_by_human"
    remember(view.stance, view.confidence, thesis, view.model_dump(),
             [{"action": outcome, "approval_id": approval_id}], doc_ids)
    h.set_output({"outcome": outcome, "approval_id": approval_id})
    return {"outcome": outcome, "approval_id": approval_id}


def _new_documents(ticker: str, last_as_of: datetime | None, as_of: datetime, exclude: set[str]):
    lo = last_as_of.timestamp() if last_as_of else 0.0
    hi = as_of.timestamp()
    with SessionLocal() as s:
        docs = s.execute(
            select(Document).where(
                Document.ticker == ticker,
                Document.published_ts > lo,
                Document.published_ts <= hi,
            )
        ).scalars().all()
    return [d for d in docs if d.id not in exclude]


def _chunks_for_docs(doc_ids: list[str], ticker: str, as_of: datetime) -> list[RetrievedChunk]:
    """Load a document's own chunks as RetrievedChunks, guardrail-checked the same
    way the retriever checks search hits (injection quarantine + lookahead bound)."""
    as_of_ts = as_of.timestamp()
    with SessionLocal() as s:
        chunk_rows = s.execute(
            select(Chunk).where(Chunk.document_id.in_(doc_ids)).order_by(Chunk.ordinal)
        ).scalars().all()
        docs = {d.id: d for d in s.execute(
            select(Document).where(Document.id.in_(doc_ids))
        ).scalars().all()}

    out: list[RetrievedChunk] = []
    for c in chunk_rows:
        if c.published_ts > as_of_ts:
            continue
        d = docs.get(c.document_id)
        out.append(RetrievedChunk(
            chunk_id=c.id, text=c.text, source=d.source_url if d else "",
            form_type=d.form_type if d else "", published_date=d.published_date if d else "",
            published_ts=c.published_ts, score=1.0,
        ))

    clean, quarantined = scan(out)
    if quarantined:
        with span("GUARDRAIL", "injection_scan", ticker=ticker) as h:
            h.set(status="REJECTED")
            h.set_output({"quarantined": [c.chunk_id for c in quarantined]})
    assert_no_lookahead(
        [{"chunk_id": c.chunk_id, "published_ts": c.published_ts} for c in clean], as_of_ts
    )
    return clean

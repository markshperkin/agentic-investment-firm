from datetime import datetime

from app.agents.pm import PMAgent
from app.agents.research import ResearchAgent
from app.agents.risk import RiskAgent
from app.agents.schemas import NoTrade, TradeProposal
from app.config import get_settings
from app.data import price_feed
from app.firm import memory
from app.firm.hitl import submit_for_approval
from app.guardrails import risk_engine
from app.llm.router import LLMRouter
from app.obs.spans import span
from app.rag.crag import run_crag
from app.rag.retriever import Retriever
from app.state.broker import PaperBroker
from app.state.portfolio import account_snapshot


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
    settings = get_settings()
    price = price_feed.price_at(as_of.date().isoformat(), ticker, as_of)

    def _remember(stance, confidence, thesis, view, decision_log):
        snap = account_snapshot(ticker, price or 0.0)
        memory.record(
            run_id=run_id, ticker=ticker, tick_seq=tick_seq, as_of=as_of.isoformat(),
            stance=stance, confidence=confidence, current_view=view, open_thesis=thesis,
            position_qty=snap["position_qty"], cost_basis=0.0,
            last_decision_price=price, processed_doc_ids=[], decision_log=decision_log,
            dispatch_path=dispatch_path,
        )

    with span("AGENT", f"pipeline:{ticker}", agent="pipeline", ticker=ticker,
              input={"path": dispatch_path, "as_of": as_of.isoformat()}) as h:
        if price is None:
            _remember("INSUFFICIENT_EVIDENCE", 0.0, "no price", None, [{"action": "skip_no_price"}])
            h.set_output({"outcome": "no_price"})
            return {"outcome": "no_price"}

        crag = run_crag(ticker=ticker, as_of=as_of, intent=intent, retriever=retriever, router=router)
        if crag.status != "OK":
            _remember("INSUFFICIENT_EVIDENCE", 0.0, "insufficient evidence", None,
                      [{"action": "refuse", "reason": "insufficient_evidence"}])
            h.set_output({"outcome": "insufficient_evidence"})
            return {"outcome": "insufficient_evidence"}

        view = ResearchAgent(router).analyze(ticker, as_of, crag.chunks)
        if view.stance in ("INSUFFICIENT_EVIDENCE", "NEUTRAL"):
            _remember(view.stance, view.confidence, "no actionable view", view.model_dump(),
                      [{"action": "no_trade", "reason": view.stance}])
            h.set_output({"outcome": "no_actionable_view", "stance": view.stance})
            return {"outcome": "no_actionable_view"}

        snap = account_snapshot(ticker, price)
        decision = PMAgent(router).decide(view, equity=snap["equity"], cash=snap["cash"], price=price)
        if isinstance(decision, NoTrade):
            _remember(view.stance, view.confidence, "PM no-trade", view.model_dump(),
                      [{"action": "no_trade", "reason": decision.reason}])
            h.set_output({"outcome": "no_trade", "reason": decision.reason})
            return {"outcome": "no_trade"}

        return _risk_and_route(run_id, decision, view, price, as_of, dispatch_path,
                               tick_seq, router, h, _remember)


def _risk_and_route(run_id, proposal: TradeProposal, view, price, as_of, dispatch_path,
                    tick_seq, router, h, _remember) -> dict:
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
        _remember(view.stance, view.confidence, thesis, view.model_dump(),
                  [{"action": "rejected", "breaches": engine.breaches}])
        h.set_output({"outcome": "rejected", "breaches": engine.breaches})
        return {"outcome": "rejected", "breaches": engine.breaches}

    if engine.decision == "AUTO_APPROVE":
        fill = PaperBroker().execute(ticker=proposal.ticker, side=proposal.side,
                                     quantity=proposal.quantity, reference_price=price, as_of=as_of)
        _remember(view.stance, view.confidence, thesis, view.model_dump(),
                  [{"action": "auto_executed", "trade_id": fill.trade_id}])
        h.set_output({"outcome": "auto_executed", "trade_id": fill.trade_id})
        return {"outcome": "auto_executed", "trade_id": fill.trade_id}

    # REQUIRE_HUMAN
    narrative = RiskAgent(router).narrate(proposal, engine)
    approval_id = submit_for_approval(run_id=run_id, proposal=proposal, reference_price=price,
                                      as_of=as_of.isoformat(), reasoning=narrative.reasoning)
    _remember(view.stance, view.confidence, thesis, view.model_dump(),
              [{"action": "awaiting_approval", "approval_id": approval_id}])
    h.set_output({"outcome": "awaiting_approval", "approval_id": approval_id})
    return {"outcome": "awaiting_approval", "approval_id": approval_id}

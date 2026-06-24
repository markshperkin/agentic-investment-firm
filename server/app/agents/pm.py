from app.agents.schemas import NoTrade, PMDecision, ResearchView, TradeProposal
from app.config import get_settings
from app.llm.router import LLMRouter
from app.obs.spans import span
from app.state.sizing import position_sizer

SYSTEM = (
    "You are a portfolio manager. Given a grounded research view, decide BUY, SELL, "
    "or HOLD and write a thesis card (headline, why now, expected edge, risks). "
    "Ground every claim in the view's evidence. You do not choose position size — "
    "that is computed deterministically."
)


class PMAgent:
    def __init__(self, router: LLMRouter):
        self.router = router

    def decide(
        self,
        view: ResearchView,
        *,
        equity: float,
        cash: float,
        price: float,
    ) -> TradeProposal | NoTrade:
        settings = get_settings()
        with span("AGENT", "pm", agent="pm", ticker=view.ticker,
                  input={"stance": view.stance, "confidence": view.confidence}) as h:
            if view.stance in ("INSUFFICIENT_EVIDENCE", "NEUTRAL") or \
                    view.confidence < settings.act_confidence_threshold:
                out = NoTrade(reason=f"stance={view.stance}, confidence={view.confidence}")
                h.set_output(out.model_dump())
                return out

            decision: PMDecision = self.router.complete(
                "pm", system=SYSTEM, prompt=self._prompt(view), schema=PMDecision
            ).value

            if decision.action == "HOLD":
                out = NoTrade(reason="PM chose to hold")
                h.set_output(out.model_dump())
                return out

            qty = position_sizer(
                confidence=view.confidence, equity=equity, price=price, cash=cash,
                max_position_pct=settings.max_position_pct,
                max_order_notional=settings.max_order_notional,
            )
            if qty <= 0:
                out = NoTrade(reason="size rounds to zero / insufficient cash")
                h.set_output(out.model_dump())
                return out

            proposal = TradeProposal(
                ticker=view.ticker, side=decision.action, quantity=qty,
                est_notional=round(qty * price, 2), thesis_card=decision.thesis_card,
            )
            h.set_output(proposal.model_dump())
            return proposal

    @staticmethod
    def _prompt(view: ResearchView) -> str:
        points = "\n".join(f"- {kp.text} [cite {kp.citation.chunk_id}]" for kp in view.key_points)
        return (
            f"Ticker: {view.ticker}\nStance: {view.stance}\nConfidence: {view.confidence}\n"
            f"Grounded key points:\n{points}\n\nDecide BUY/SELL/HOLD and write the thesis card."
        )

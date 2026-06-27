from app.agents.schemas import NoTrade, PMDecision, ResearchView, TradeProposal
from app.config import get_settings
from app.llm.router import LLMRouter
from app.obs.spans import span
from app.state.sizing import position_sizer

SYSTEM = (
    "You are a portfolio manager. Given a grounded research view, decide BUY, SELL, "
    "or HOLD and write a thesis card (headline, why now, expected edge, risks). "
    "SELL closes an existing long position (the book is long-only — never sell short); "
    "if you hold no position, do not SELL. "
    "Ground every claim in the view's evidence. You do not choose position size — "
    "that is computed deterministically. For a BUY, also set the protective exit bounds "
    "as fractions of the entry price: stop_loss_pct (downside you will accept before a "
    "forced exit) and take_profit_pct (upside at which you take profit). Size both to your "
    "conviction; the firm hard-caps stop_loss_pct at 4% and take_profit_pct at 10%, and "
    "values beyond the caps are clamped."
)


def clamp_bounds(stop_loss_pct: float, take_profit_pct: float, settings) -> tuple[float, float]:
    """Hard guardrail: keep PM-proposed exit bounds inside the firm's risk caps."""
    stop = min(max(stop_loss_pct, settings.min_bound_pct), settings.max_stop_loss_pct)
    target = min(max(take_profit_pct, settings.min_bound_pct), settings.max_take_profit_pct)
    return round(stop, 4), round(target, 4)


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
        position_qty: int = 0,
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
                "pm", system=SYSTEM, prompt=self._prompt(view, position_qty), schema=PMDecision
            ).value

            if decision.action == "HOLD":
                out = NoTrade(reason="PM chose to hold")
                h.set_output(out.model_dump())
                return out

            if decision.action == "SELL":
                # A discretionary exit closes the whole held position — the sizer prices
                # new entries, not exits, so it must not size a sell.
                if position_qty <= 0:
                    out = NoTrade(reason="SELL with no open position to close")
                    h.set_output(out.model_dump())
                    return out
                qty = position_qty
            else:  # BUY
                qty = position_sizer(
                    confidence=view.confidence, equity=equity, price=price, cash=cash,
                    max_position_pct=settings.max_position_pct,
                )
                if qty <= 0:
                    out = NoTrade(reason="size rounds to zero / insufficient cash")
                    h.set_output(out.model_dump())
                    return out

            stop, target = clamp_bounds(decision.stop_loss_pct, decision.take_profit_pct, settings)
            proposal = TradeProposal(
                ticker=view.ticker, side=decision.action, quantity=qty,
                est_notional=round(qty * price, 2), thesis_card=decision.thesis_card,
                stop_loss_pct=stop, take_profit_pct=target,
            )
            h.set_output(proposal.model_dump())
            return proposal

    @staticmethod
    def _prompt(view: ResearchView, position_qty: int = 0) -> str:
        points = "\n".join(f"- {kp.text} [cite {kp.citation.chunk_id}]" for kp in view.key_points)
        holding = (f"You currently hold {position_qty} shares of {view.ticker}."
                   if position_qty > 0 else f"You hold no position in {view.ticker}.")
        return (
            f"Ticker: {view.ticker}\nStance: {view.stance}\nConfidence: {view.confidence}\n"
            f"{holding}\n"
            f"Grounded key points:\n{points}\n\n"
            "Decide BUY/SELL/HOLD and write the thesis card. SELL closes the position you hold."
        )

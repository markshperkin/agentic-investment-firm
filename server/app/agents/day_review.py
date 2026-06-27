from app.agents.schemas import EodDecision, ResearchView
from app.llm.router import LLMRouter
from app.obs.spans import span

SYSTEM = (
    "You are a portfolio manager running the end-of-day review. The market is about "
    "to close and positions will carry overnight gap risk. Given the open position, "
    "the day's price action, and the standing thesis, decide HOLD (conviction intact), "
    "TRIM (reduce exposure), or FLATTEN (close before the close). Justify the choice in "
    "terms of gap risk and whether the thesis still holds. You do not choose sizes."
)


class DayReviewAgent:
    def __init__(self, router: LLMRouter):
        self.router = router

    def decide(
        self,
        *,
        ticker: str,
        position_qty: int,
        price_features: dict,
        prior_view: ResearchView | None,
        delta_points: list[str],
    ) -> EodDecision:
        with span("AGENT", "day_review", agent="day_review", ticker=ticker,
                  input={"position_qty": position_qty, "pct_change": price_features.get("pct_change")}) as h:
            decision = self.router.complete(
                "day_review", system=SYSTEM, prompt=self._prompt(ticker, position_qty, price_features,
                                                                 prior_view, delta_points),
                schema=EodDecision,
            ).value
            h.set_output(decision.model_dump())
            return decision

    @staticmethod
    def _prompt(ticker, position_qty, price_features, prior_view, delta_points) -> str:
        thesis = ""
        if prior_view is not None:
            pts = "\n".join(f"- {kp.text}" for kp in prior_view.key_points)
            thesis = f"Standing view: {prior_view.stance} (conf {prior_view.confidence})\n{pts}\n"
        delta = "\n".join(f"- {d}" for d in delta_points) or "(none)"
        return (
            f"Ticker: {ticker}\nOpen position: {position_qty} shares\n"
            f"Day price action: {price_features}\n{thesis}"
            f"New evidence since last decision:\n{delta}\n\n"
            "Decide HOLD / TRIM / FLATTEN for the close."
        )

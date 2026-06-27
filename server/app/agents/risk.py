from app.agents.schemas import RiskNarrative, TradeProposal
from app.guardrails.risk_engine import RiskEngineResult
from app.llm.router import LLMRouter
from app.obs.spans import span

SYSTEM = (
    "You are a risk officer. Explain, for the human Risk Committee, why a proposed "
    "trade needs sign-off: summarise the thesis and the key risks plainly. You cannot "
    "approve or change limits — the deterministic engine already decided that."
)


class RiskAgent:
    def __init__(self, router: LLMRouter):
        self.router = router

    def narrate(self, proposal: TradeProposal, engine: RiskEngineResult) -> RiskNarrative:
        with span("AGENT", "risk_narrator", agent="risk_narrator", ticker=proposal.ticker,
                  input={"engine_decision": engine.decision}):
            prompt = (
                f"Proposed: {proposal.side} {proposal.quantity} {proposal.ticker} "
                f"(~${proposal.est_notional:.0f}).\n"
                f"Thesis: {proposal.thesis_card.headline} — {proposal.thesis_card.why_now}\n"
                f"Risks: {proposal.thesis_card.risks}\n"
                "Write the risk narrative for the committee."
            )
            return self.router.complete("risk_narrator", system=SYSTEM, prompt=prompt,
                                        schema=RiskNarrative).value

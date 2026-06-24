from datetime import datetime

from app.agents.schemas import QueryPlan
from app.llm.router import LLMRouter

SYSTEM = (
    "You plan retrieval queries over an SEC EDGAR filings corpus for an equity "
    "research desk. Produce focused queries. When given a critique of a failed "
    "retrieval, reason from its failure_kind to fix it (broaden, narrow, adjust the "
    "date window, decompose, or rephrase). Never reuse a query already tried."
)


class QueryGenAgent:
    def __init__(self, router: LLMRouter):
        self.router = router

    def plan(
        self,
        ticker: str,
        as_of: datetime,
        intent: str,
        prior_queries: list[str] | None = None,
        critique: dict | None = None,
    ) -> QueryPlan:
        prompt = (
            f"Ticker: {ticker}\n"
            f"As of: {as_of.isoformat()}\n"
            f"Intent: {intent}\n"
            f"Queries already tried (do not repeat): {prior_queries or []}\n"
            f"Critique of last retrieval: {critique or 'none'}\n"
            "Return a query plan."
        )
        return self.router.complete("query_gen", system=SYSTEM, prompt=prompt, schema=QueryPlan).value

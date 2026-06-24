from dataclasses import dataclass, field
from datetime import datetime

from app.agents.query_gen import QueryGenAgent
from app.agents.relevance_critic import RelevanceCriticAgent
from app.agents.schemas import QueryPlan
from app.llm.router import LLMRouter
from app.obs.spans import span
from app.rag.retriever import RetrievedChunk, Retriever


@dataclass
class CragResult:
    status: str  # OK | INSUFFICIENT_EVIDENCE
    chunks: list[RetrievedChunk] = field(default_factory=list)
    attempts: list[dict] = field(default_factory=list)


def _retrieve_for_plan(retriever: Retriever, plan: QueryPlan, ticker: str,
                       as_of: datetime, k: int) -> list[RetrievedChunk]:
    merged: dict[str, RetrievedChunk] = {}
    for q in plan.queries:
        for c in retriever.retrieve(q, ticker, as_of, k):
            if c.chunk_id not in merged or c.score > merged[c.chunk_id].score:
                merged[c.chunk_id] = c
    return sorted(merged.values(), key=lambda c: c.score, reverse=True)[:k]


def run_crag(
    *,
    ticker: str,
    as_of: datetime,
    intent: str,
    retriever: Retriever,
    router: LLMRouter,
    k: int = 5,
    max_retries: int = 2,
) -> CragResult:
    """Corrective retrieval: plan -> retrieve -> grade -> (reformulate from the
    critique, bounded) -> chunks, or an honest INSUFFICIENT_EVIDENCE refusal.
    Retries only on bad retrieval, never on a negative decision."""
    query_gen = QueryGenAgent(router)
    critic = RelevanceCriticAgent(router)

    tried: list[str] = []
    critique: dict | None = None
    result = CragResult(status="INSUFFICIENT_EVIDENCE")

    with span("AGENT", "crag", agent="crag", ticker=ticker, input={"intent": intent}):
        for attempt in range(max_retries + 1):
            plan = query_gen.plan(ticker, as_of, intent, prior_queries=tried, critique=critique)
            tried.extend(plan.queries)
            chunks = _retrieve_for_plan(retriever, plan, ticker, as_of, k)
            grade = critic.grade(plan.queries[0], chunks)

            with span("RETRIEVAL_ATTEMPT", f"attempt:{attempt}", ticker=ticker,
                      input={"queries": plan.queries, "strategy": plan.strategy}) as h:
                h.set_output({
                    "chunk_ids": [c.chunk_id for c in chunks],
                    "relevant": grade.relevant,
                    "failure_kind": grade.failure_kind,
                })

            result.attempts.append({
                "queries": plan.queries, "strategy": plan.strategy,
                "chunk_ids": [c.chunk_id for c in chunks],
                "relevant": grade.relevant, "failure_kind": grade.failure_kind,
            })

            if grade.relevant:
                return CragResult(status="OK", chunks=chunks, attempts=result.attempts)
            critique = grade.model_dump()

    return result

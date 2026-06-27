from app.agents.schemas import RelevanceGrade
from app.llm.router import LLMRouter
from app.rag.retriever import RetrievedChunk

SYSTEM = (
    "You judge whether retrieved SEC filing excerpts give a portfolio manager ENOUGH "
    "to form a directional view on the ticker. You are grading for a trading decision, "
    "not auditing financial statements. Mark relevant=true if the excerpts contain ANY "
    "decision-useful evidence — a growth rate, guidance, a margin/segment trend, a "
    "material event, or a risk that changes the thesis. You do NOT need the full "
    "consolidated statements or exact line items; a clear directional signal (e.g. "
    "'Data Center revenue up 142%') is sufficient. Only mark relevant=false when the "
    "excerpts are off-topic, the wrong entity, or contain no decision-useful facts. "
    "Set coverage to how much decision-useful signal is present, and on a true miss "
    "give a failure_kind + concrete fix_hint so the next query can be corrected."
)


class RelevanceCriticAgent:
    def __init__(self, router: LLMRouter):
        self.router = router

    def grade(self, query: str, chunks: list[RetrievedChunk]) -> RelevanceGrade:
        excerpts = "\n\n".join(f"[{c.chunk_id}] ({c.form_type} {c.published_date})\n{c.text[:2500]}"
                               for c in chunks) or "(no chunks retrieved)"
        prompt = f"Query: {query}\n\nRetrieved excerpts:\n{excerpts}\n\nGrade the relevance."
        return self.router.complete("relevance_critic", system=SYSTEM, prompt=prompt,
                                    schema=RelevanceGrade).value

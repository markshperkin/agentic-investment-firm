from app.agents.schemas import RelevanceGrade
from app.llm.router import LLMRouter
from app.rag.retriever import RetrievedChunk

SYSTEM = (
    "You judge whether retrieved SEC filing excerpts actually answer a research "
    "query. If they do not, explain why with a failure_kind and a concrete fix_hint "
    "so the next query can be corrected. Fail safe toward MORE grounding: when "
    "unsure, mark relevant=false."
)


class RelevanceCriticAgent:
    def __init__(self, router: LLMRouter):
        self.router = router

    def grade(self, query: str, chunks: list[RetrievedChunk]) -> RelevanceGrade:
        excerpts = "\n\n".join(f"[{c.chunk_id}] ({c.form_type} {c.published_date})\n{c.text[:500]}"
                               for c in chunks) or "(no chunks retrieved)"
        prompt = f"Query: {query}\n\nRetrieved excerpts:\n{excerpts}\n\nGrade the relevance."
        return self.router.complete("relevance_critic", system=SYSTEM, prompt=prompt,
                                    schema=RelevanceGrade).value

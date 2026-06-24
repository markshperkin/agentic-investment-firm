from datetime import datetime

from app.agents.schemas import ResearchView
from app.guardrails.citations import verify_view
from app.llm.router import LLMRouter
from app.obs.spans import span
from app.rag.retriever import RetrievedChunk

SYSTEM = (
    "You are an equity research analyst. From the SEC filing excerpts only, form a "
    "grounded view. Every key point MUST cite a chunk_id from the excerpts and may "
    "only state numbers that appear in that excerpt. If the evidence is insufficient, "
    "return stance INSUFFICIENT_EVIDENCE with no key points."
)


class ResearchAgent:
    def __init__(self, router: LLMRouter):
        self.router = router

    def analyze(
        self,
        ticker: str,
        as_of: datetime,
        chunks: list[RetrievedChunk],
        price_features: dict | None = None,
    ) -> ResearchView:
        excerpts = "\n\n".join(
            f"[{c.chunk_id}] ({c.form_type} {c.published_date})\n{c.text[:600]}" for c in chunks
        ) or "(no excerpts)"
        prompt = (
            f"Ticker: {ticker}\nAs of: {as_of.isoformat()}\n"
            f"Price features: {price_features or {}}\n\nExcerpts:\n{excerpts}\n\n"
            "Return a grounded research view."
        )
        view = self.router.complete("research", system=SYSTEM, prompt=prompt, schema=ResearchView).value

        with span("GUARDRAIL", "citation_check", agent="research", ticker=ticker) as h:
            before = len(view.key_points)
            view = verify_view(view, chunks)
            h.set(status="OK" if view.stance != "INSUFFICIENT_EVIDENCE" else "REJECTED")
            h.set_output({"points_before": before, "points_kept": len(view.key_points),
                          "final_stance": view.stance})
        return view

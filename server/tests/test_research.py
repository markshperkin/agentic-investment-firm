from datetime import datetime

from app.agents.research import ResearchAgent
from app.agents.schemas import Citation, KeyPoint, ResearchView
from app.guardrails.citations import verify_view
from app.llm.base import ProviderResult
from app.llm.router import LLMRouter
from app.obs.spans import start_run
from app.rag.retriever import RetrievedChunk

CHUNK = RetrievedChunk(
    chunk_id="d:0", text="Nvidia reported data center revenue of 22.6 billion, up 427 percent.",
    source="http://e/a", form_type="8-K", published_date="2024-05-20", published_ts=0.0, score=0.9,
)


def _view(points):
    return ResearchView(ticker="NVDA", stance="BULLISH", confidence=0.8, key_points=points)


def test_verifier_keeps_supported_drops_fabricated_number():
    good = KeyPoint(text="Data center revenue was 22.6 billion.",
                    citation=Citation(chunk_id="d:0"))
    bad_number = KeyPoint(text="Revenue was 99.9 billion.", citation=Citation(chunk_id="d:0"))
    out = verify_view(_view([good, bad_number]), [CHUNK])
    assert len(out.key_points) == 1
    assert out.key_points[0].text.startswith("Data center")
    assert out.stance == "BULLISH"


def test_verifier_drops_fabricated_citation():
    bad_cite = KeyPoint(text="Revenue rose.", citation=Citation(chunk_id="does-not-exist"))
    out = verify_view(_view([bad_cite]), [CHUNK])
    assert out.key_points == []
    assert out.stance == "INSUFFICIENT_EVIDENCE"  # bullish with no grounding -> refuse


def test_research_agent_applies_verifier():
    start_run("test")
    payload = {
        "ticker": "NVDA", "stance": "BULLISH", "confidence": 0.8,
        "key_points": [
            {"text": "Data center revenue 22.6 billion.", "citation": {"chunk_id": "d:0"}},
            {"text": "Made-up 500 billion figure.", "citation": {"chunk_id": "d:0"}},
        ],
    }
    router = LLMRouter(provider=_Scripted(payload))
    view = ResearchAgent(router).analyze("NVDA", datetime(2024, 5, 23, 10, 0), [CHUNK])
    assert len(view.key_points) == 1  # fabricated 500 billion stripped


class _Scripted:
    def __init__(self, data):
        self.data = data

    def complete(self, model, system, prompt, schema):
        return ProviderResult(data=self.data, prompt_tokens=1, completion_tokens=1)

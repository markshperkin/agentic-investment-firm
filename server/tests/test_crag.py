from datetime import datetime

from app.llm.base import ProviderResult
from app.llm.router import LLMRouter
from app.obs.spans import start_run
from app.rag.crag import run_crag
from app.rag.edgar import FakeFilingSource, RawFiling
from app.rag.embeddings import FakeEmbedder
from app.rag.ingest import CorpusIngester
from app.rag.retriever import Retriever
from app.rag.vector_store import InMemoryVectorStore

AS_OF = datetime(2024, 5, 23, 15, 0)


class ScriptedProvider:
    """Returns canned structured payloads in call order."""

    def __init__(self, payloads: list[dict]):
        self._payloads = list(payloads)

    def complete(self, model, system, prompt, schema):
        data = self._payloads.pop(0)
        return ProviderResult(data=data, prompt_tokens=1, completion_tokens=1)


def _retriever():
    embedder = FakeEmbedder()
    store = InMemoryVectorStore()
    filings = [RawFiling("NVDA", "8-K", "http://e/a", datetime(2024, 5, 20, 16, 0),
                         "Nvidia reports record data center revenue and raises guidance.")]
    CorpusIngester(FakeFilingSource(filings), embedder, store).ingest("2024-05-23", ["NVDA"])
    return Retriever(embedder, store)


PLAN = {"queries": ["nvidia data center revenue guidance"], "strategy": "BASELINE"}
PLAN2 = {"queries": ["nvidia quarterly revenue results"], "strategy": "STEPBACK"}
GOOD = {"relevant": True, "coverage": 0.9, "failure_kind": "NONE"}
BAD = {"relevant": False, "coverage": 0.1, "missing": "no figures", "failure_kind": "STALE",
       "fix_hint": "widen date window"}


def test_crag_succeeds_first_try():
    start_run("test")
    router = LLMRouter(provider=ScriptedProvider([PLAN, GOOD]))
    res = run_crag(ticker="NVDA", as_of=AS_OF, intent="RESEARCH_ENTRY",
                   retriever=_retriever(), router=router)
    assert res.status == "OK"
    assert len(res.attempts) == 1
    assert res.chunks


def test_crag_retries_then_succeeds():
    start_run("test")
    router = LLMRouter(provider=ScriptedProvider([PLAN, BAD, PLAN2, GOOD]))
    res = run_crag(ticker="NVDA", as_of=AS_OF, intent="RESEARCH_ENTRY",
                   retriever=_retriever(), router=router)
    assert res.status == "OK"
    assert len(res.attempts) == 2
    assert res.attempts[0]["failure_kind"] == "STALE"


def test_crag_exhausts_to_refusal():
    start_run("test")
    router = LLMRouter(provider=ScriptedProvider([PLAN, BAD, PLAN2, BAD, PLAN, BAD]))
    res = run_crag(ticker="NVDA", as_of=AS_OF, intent="RESEARCH_ENTRY",
                   retriever=_retriever(), router=router, max_retries=2)
    assert res.status == "INSUFFICIENT_EVIDENCE"
    assert len(res.attempts) == 3

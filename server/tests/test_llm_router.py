import tempfile
from pathlib import Path

from pydantic import BaseModel

from app.llm.base import ProviderResult
from app.llm.providers.cassette import CassetteProvider
from app.llm.router import HAIKU, SONNET, LLMRouter
from app.obs import spans


class Stance(BaseModel):
    stance: str
    confidence: float


def test_routing_picks_model_tier():
    router = LLMRouter(provider=CassetteProvider())
    assert router.model_for("research") == HAIKU
    assert router.model_for("pm") == SONNET
    assert router.model_for("risk") == SONNET


def test_cassette_roundtrip_validates_and_costs_and_traces():
    with tempfile.TemporaryDirectory() as d:
        cas = CassetteProvider(cassette_dir=Path(d))
        system, prompt = "you are research", "analyze NVDA"
        cas.save(
            "claude-haiku-4-5",
            system,
            prompt,
            ProviderResult(data={"stance": "BULLISH", "confidence": 0.7},
                           prompt_tokens=1000, completion_tokens=200),
        )

        router = LLMRouter(provider=cas)
        run_id = spans.start_run(kind="test")
        res = router.complete("research", system=system, prompt=prompt, schema=Stance)
        spans.end_run(run_id)

    assert isinstance(res.value, Stance)
    assert res.value.stance == "BULLISH"
    assert res.model == "claude-haiku-4-5"
    assert res.cost_usd > 0
    assert res.cache_hit is True

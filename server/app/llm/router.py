from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.llm.base import LLMResult, Provider
from app.llm.pricing import price
from app.obs.spans import span

T = TypeVar("T", bound=BaseModel)

HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-4-6"

# Cost-aware routing. LLM steps do judgment/synthesis on Haiku; the hard *decisions* are
# deterministic (risk engine, sizer, bound clamps) with humans gating large trades. SONNET
# stays available to escalate a step here if an eval ever shows Haiku is insufficient.
TASK_MODEL: dict[str, str] = {
    "query_gen": HAIKU,
    "relevance_critic": HAIKU,
    "research": HAIKU,
    "reporting": HAIKU,
    "day_review": HAIKU,
    "pm": HAIKU,
    "risk_narrator": HAIKU,
}


def _build_provider() -> Provider:
    settings = get_settings()
    if settings.llm_mode == "cassette":
        from app.llm.providers.cassette import CassetteProvider

        return CassetteProvider()
    from app.llm.providers.anthropic import AnthropicProvider

    if not settings.anthropic_api_key:
        raise RuntimeError("LLM_MODE=live requires ANTHROPIC_API_KEY")
    return AnthropicProvider(api_key=settings.anthropic_api_key)


class LLMRouter:
    def __init__(self, provider: Provider | None = None):
        self.provider = provider or _build_provider()

    def model_for(self, task: str) -> str:
        return TASK_MODEL.get(task, HAIKU)

    def complete(self, task: str, *, system: str, prompt: str, schema: Type[T]) -> LLMResult[T]:
        from app.guardrails import budget

        model = self.model_for(task)
        with span("LLM", f"llm:{task}", agent=task, input={"prompt_chars": len(prompt)}) as h:
            # One retry: a malformed structured output (e.g. the model leaking tool-call
            # tags into a field) is usually transient — re-asking yields a clean parse.
            result = value = None
            for attempt in range(2):
                budget.charge_call()
                result = self.provider.complete(model, system, prompt, schema)
                budget.charge_tokens(result.prompt_tokens + result.completion_tokens)
                try:
                    value = schema.model_validate(result.data)
                    break
                except ValidationError:
                    if attempt == 1:
                        raise
            cost = price(model, result.prompt_tokens, result.completion_tokens)
            h.set(
                model=model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                cost_usd=cost,
                cache_hit=result.cache_hit,
            )
            h.set_output(value.model_dump())
            return LLMResult(
                value=value,
                model=model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                cost_usd=cost,
                cache_hit=result.cache_hit,
            )

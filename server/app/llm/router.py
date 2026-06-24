from typing import Type, TypeVar

from pydantic import BaseModel

from app.config import get_settings
from app.llm.base import LLMResult, Provider
from app.llm.pricing import price
from app.obs.spans import span

T = TypeVar("T", bound=BaseModel)

HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-4-6"

# Cost-aware routing: cheap model by default, escalate the hard reasoning.
TASK_MODEL: dict[str, str] = {
    "query_gen": HAIKU,
    "relevance_critic": HAIKU,
    "research": HAIKU,
    "reporting": HAIKU,
    "pm": SONNET,
    "risk": SONNET,
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
        model = self.model_for(task)
        with span("LLM", f"llm:{task}", agent=task, input={"prompt_chars": len(prompt)}) as h:
            result = self.provider.complete(model, system, prompt, schema)
            value = schema.model_validate(result.data)
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

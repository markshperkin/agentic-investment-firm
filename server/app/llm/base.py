from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class ProviderResult:
    data: dict
    prompt_tokens: int
    completion_tokens: int
    cache_hit: bool = False


@dataclass
class LLMResult(Generic[T]):
    value: T
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    cache_hit: bool


class Provider(Protocol):
    def complete(self, model: str, system: str, prompt: str, schema: type[BaseModel]) -> ProviderResult:
        ...

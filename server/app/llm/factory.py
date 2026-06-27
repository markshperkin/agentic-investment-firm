from functools import lru_cache

from app.llm.router import LLMRouter


@lru_cache
def get_router() -> LLMRouter:
    return LLMRouter()

import time
from contextvars import ContextVar
from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    """Per-run resource cap hit. Halts the run cleanly rather than letting cost or
    loops run away."""


@dataclass
class Budget:
    max_calls: int
    max_tokens: int
    max_seconds: int
    calls: int = 0
    tokens: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def check_call(self) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"max LLM calls {self.max_calls} reached")
        if time.monotonic() - self.started_at > self.max_seconds:
            raise BudgetExceeded(f"max run seconds {self.max_seconds} reached")
        self.calls += 1

    def add_tokens(self, n: int) -> None:
        self.tokens += n
        if self.tokens > self.max_tokens:
            raise BudgetExceeded(f"max tokens {self.max_tokens} reached")


_current: ContextVar[Budget | None] = ContextVar("current_budget", default=None)


def start(budget: Budget) -> None:
    _current.set(budget)


def clear() -> None:
    _current.set(None)


def charge_call() -> None:
    b = _current.get()
    if b is not None:
        b.check_call()


def charge_tokens(n: int) -> None:
    b = _current.get()
    if b is not None:
        b.add_tokens(n)

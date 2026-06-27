# Approximate per-million-token USD prices (input, output). Configurable —
# only used for the per-run cost accounting / cost-aware-routing story.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
}


def price(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return round(prompt_tokens / 1_000_000 * pin + completion_tokens / 1_000_000 * pout, 6)

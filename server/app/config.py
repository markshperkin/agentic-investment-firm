from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Agentic Investment Firm"
    llm_mode: Literal["live", "cassette"] = "cassette"
    anthropic_api_key: str = ""
    voyage_api_key: str = ""
    database_url: str = "sqlite:///./data/firm.sqlite"
    log_level: str = "INFO"

    starting_cash: float = 1_000_000.0
    slippage_bps: float = 5.0
    commission_per_trade: float = 1.0

    tick_interval_minutes: int = 60
    price_move_threshold: float = 0.02
    act_confidence_threshold: float = 0.6
    relevance_min_coverage: float = 0.3
    max_position_pct: float = 0.10                 # deterministic sizer: max % of equity/order
    approval_notional_threshold: float = 25_000.0  # >= this notional -> human approval + pause
    approval_timeout_seconds: int = 1800           # how long a paused run waits for a decision

    # Per-position protective bounds. The PM proposes a stop/target per BUY; the values
    # are clamped to the max caps below, then stored on the position and enforced
    # deterministically each tick. The plain *_pct values are the fallback used when a
    # position carries no PM-set bound.
    stop_loss_pct: float = 0.04
    take_profit_pct: float = 0.10
    max_stop_loss_pct: float = 0.04
    max_take_profit_pct: float = 0.10
    min_bound_pct: float = 0.005
    trim_fraction: float = 0.5

    max_llm_calls_per_run: int = 200
    max_tokens_per_run: int = 500_000
    max_run_seconds: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()

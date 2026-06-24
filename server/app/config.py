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
    max_position_pct: float = 0.10
    max_order_notional: float = 25_000.0
    max_daily_loss_pct: float = 0.03
    max_trades_per_day: int = 20

    max_llm_calls_per_run: int = 200
    max_tokens_per_run: int = 500_000
    max_run_seconds: int = 600


@lru_cache
def get_settings() -> Settings:
    return Settings()

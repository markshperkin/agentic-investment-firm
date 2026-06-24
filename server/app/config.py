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


@lru_cache
def get_settings() -> Settings:
    return Settings()

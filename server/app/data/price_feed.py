from datetime import datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.data.prices import PRICES_DIR


@lru_cache(maxsize=128)
def _load(replay_date: str, ticker: str, prices_dir: str) -> pd.DataFrame:
    path = Path(prices_dir) / replay_date / f"{ticker}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No price data for {ticker} on {replay_date}")
    df = pd.read_parquet(path)
    return df.sort_values("ts").reset_index(drop=True)


def _bars_until(replay_date: str, ticker: str, as_of: datetime, prices_dir: Path) -> pd.DataFrame:
    df = _load(replay_date, ticker, str(prices_dir))
    # lookahead-safe: never return a bar timestamped after `as_of`
    return df[df["ts"] <= as_of]


def price_at(replay_date: str, ticker: str, as_of: datetime, prices_dir: Path | None = None) -> float | None:
    bars = _bars_until(replay_date, ticker, as_of, prices_dir or PRICES_DIR)
    if bars.empty:
        return None
    return float(bars.iloc[-1]["close"])


def price_features(
    replay_date: str, ticker: str, as_of: datetime, prices_dir: Path | None = None
) -> dict:
    bars = _bars_until(replay_date, ticker, as_of, prices_dir or PRICES_DIR)
    if bars.empty:
        return {"last_price": None, "prev_close": None, "pct_change": None, "n_bars": 0}
    last = float(bars.iloc[-1]["close"])
    first = float(bars.iloc[0]["close"])
    pct = (last - first) / first if first else None
    return {
        "last_price": round(last, 4),
        "prev_close": round(first, 4),
        "pct_change": round(pct, 6) if pct is not None else None,
        "n_bars": int(len(bars)),
    }


def clear_cache() -> None:
    _load.cache_clear()

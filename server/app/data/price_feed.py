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
    """Intraday features as of `as_of`. `pct_change` is the move since the replay
    day's OPEN — anchored to the day so any stray off-day bar can't skew it. This
    is what "how much has it moved today" means."""
    bars = _bars_until(replay_date, ticker, as_of, prices_dir or PRICES_DIR)
    if bars.empty:
        return {"last_price": None, "day_open": None, "pct_change": None, "n_bars": 0}
    day = datetime.fromisoformat(replay_date).date()
    day_bars = bars[bars["ts"].dt.date == day]
    open_px = float(day_bars.iloc[0]["close"]) if not day_bars.empty else float(bars.iloc[0]["close"])
    last = float(bars.iloc[-1]["close"])
    pct = (last - open_px) / open_px if open_px else None
    return {
        "last_price": round(last, 4),
        "day_open": round(open_px, 4),
        "pct_change": round(pct, 6) if pct is not None else None,
        "n_bars": int(len(bars)),
    }


def move_since(
    replay_date: str, ticker: str, prev_as_of: datetime | None, as_of: datetime,
    prices_dir: Path | None = None,
) -> float | None:
    """Tick-over-tick return: the change from the previous tick's price to the
    price at `as_of`. Both reads are lookahead-safe (each is the last bar ≤ its
    own timestamp). Returns None at the first tick (no previous price)."""
    if prev_as_of is None:
        return None
    prev = price_at(replay_date, ticker, prev_as_of, prices_dir)
    now = price_at(replay_date, ticker, as_of, prices_dir)
    if prev is None or now is None or prev == 0:
        return None
    return (now - prev) / prev


def clear_cache() -> None:
    _load.cache_clear()

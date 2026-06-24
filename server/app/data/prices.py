from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd

from app.data.catalog import record_asset

PRICES_DIR = Path("data/prices")
BENCHMARK = "SPY"

FetchFn = Callable[[str, datetime, datetime, str], pd.DataFrame]


def default_fetch(ticker: str, start: datetime, end: datetime, interval: str) -> pd.DataFrame:
    """Pull bars from yfinance and normalise to naive US/Eastern timestamps.
    Columns: ts, open, high, low, close, volume."""
    import yfinance as yf  # lazy: live network only

    raw = yf.download(ticker, start=start, end=end, interval=interval,
                      progress=False, auto_adjust=False)
    if raw.empty:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    raw = raw.reset_index()
    ts_col = "Datetime" if "Datetime" in raw.columns else "Date"
    ts = pd.to_datetime(raw[ts_col])
    if getattr(ts.dt, "tz", None) is not None:
        ts = ts.dt.tz_convert("US/Eastern").dt.tz_localize(None)
    return pd.DataFrame(
        {
            "ts": ts,
            "open": raw["Open"].squeeze(),
            "high": raw["High"].squeeze(),
            "low": raw["Low"].squeeze(),
            "close": raw["Close"].squeeze(),
            "volume": raw["Volume"].squeeze(),
        }
    )


class PriceIngester:
    def __init__(self, fetch: FetchFn = default_fetch, prices_dir: Path = PRICES_DIR):
        self.fetch = fetch
        self.dir = prices_dir

    def ingest(
        self,
        replay_date: str,
        tickers: list[str],
        lookback_days: int = 7,
        interval: str = "5m",
    ) -> dict[str, str]:
        day = datetime.fromisoformat(replay_date)
        start = day - timedelta(days=lookback_days)
        end = day + timedelta(days=1)
        results: dict[str, str] = {}
        for ticker in _with_benchmark(tickers):
            try:
                df = self.fetch(ticker, start, end, interval)
                if df.empty:
                    record_asset(replay_date, ticker, "PRICES", "FAILED", {"reason": "no_bars"})
                    results[ticker] = "FAILED"
                    continue
                out = self.dir / replay_date
                out.mkdir(parents=True, exist_ok=True)
                df.to_parquet(out / f"{ticker}.parquet", index=False)
                record_asset(replay_date, ticker, "PRICES", "READY", {"n_bars": int(len(df))})
                results[ticker] = "READY"
            except Exception as exc:  # noqa: BLE001
                record_asset(replay_date, ticker, "PRICES", "FAILED", {"reason": str(exc)})
                results[ticker] = "FAILED"
        return results


def _with_benchmark(tickers: list[str]) -> list[str]:
    return tickers if BENCHMARK in tickers else [*tickers, BENCHMARK]

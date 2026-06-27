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
        interval: str | None = None,
    ) -> dict[str, str]:
        day = datetime.fromisoformat(replay_date)
        interval = interval or _interval_for(day)
        # replay day only — no prior-day lookback (nothing downstream uses it)
        start = day
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
                record_asset(replay_date, ticker, "PRICES", "READY",
                             _price_detail(df, day, interval))
                results[ticker] = "READY"
            except Exception as exc:  # noqa: BLE001
                record_asset(replay_date, ticker, "PRICES", "FAILED", {"reason": str(exc)})
                results[ticker] = "FAILED"
        return results


def _with_benchmark(tickers: list[str]) -> list[str]:
    return tickers if BENCHMARK in tickers else [*tickers, BENCHMARK]


def _price_detail(df: pd.DataFrame, day: datetime, interval: str) -> dict:
    """What we stored: total bars, how many fall on the replay day vs any stray
    off-day bars Yahoo returned, the interval served, and the covered range."""
    ts = pd.to_datetime(df["ts"])
    n = int(len(df))
    current = int((ts.dt.date == day.date()).sum())
    return {
        "interval": interval,
        "n_bars": n,
        "n_bars_current_day": current,
        "n_bars_lookback": n - current,
        "first_ts": str(ts.min()),
        "last_ts": str(ts.max()),
    }


def _interval_for(day: datetime) -> str:
    """Pick the finest yfinance interval Yahoo will still serve for this date.
    Yahoo caps intraday history: sub-hour (e.g. 5m) ~60 days, hourly (60m) ~730
    days. The replay clock ticks hourly, so 60m aligns 1:1 with ticks and reaches
    ~2 years back; older than that degrades to daily bars (flat intraday)."""
    age_days = (datetime.now() - day).days
    if age_days <= 55:
        return "5m"    # finer granularity available, still > hourly ticks
    if age_days <= 725:
        return "60m"   # hourly — matches tick cadence, ~2yr reach
    return "1d"        # older than ~2yr: daily bars only

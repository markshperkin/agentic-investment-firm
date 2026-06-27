from datetime import datetime

import pandas as pd
from fastapi.testclient import TestClient

from app.data import price_feed
from app.data.prices import PriceIngester
from app.main import app


def _fake_fetch(prices_dir):
    def fetch(ticker, start, end, interval):
        # three bars on the replay day at 09:30, 12:00, 15:30
        base = {"NVDA": 100.0, "AAPL": 200.0, "SPY": 500.0}.get(ticker, 50.0)
        return pd.DataFrame(
            {
                "ts": [datetime(2024, 5, 23, 9, 30), datetime(2024, 5, 23, 12, 0),
                       datetime(2024, 5, 23, 15, 30)],
                "open": [base, base + 1, base + 2],
                "high": [base + 1, base + 2, base + 3],
                "low": [base - 1, base, base + 1],
                "close": [base, base + 5, base + 8],
                "volume": [1000, 1200, 900],
            }
        )

    return fetch


def test_ingest_writes_parquet_and_catalog(tmp_path):
    price_feed.clear_cache()
    ing = PriceIngester(fetch=_fake_fetch(tmp_path), prices_dir=tmp_path)
    results = ing.ingest("2024-05-23", ["NVDA", "AAPL"])
    assert results["NVDA"] == "READY"
    assert results["SPY"] == "READY"  # benchmark auto-added
    assert (tmp_path / "2024-05-23" / "NVDA.parquet").exists()


def test_price_feed_is_lookahead_safe(tmp_path):
    price_feed.clear_cache()
    PriceIngester(fetch=_fake_fetch(tmp_path), prices_dir=tmp_path).ingest("2024-05-23", ["NVDA"])

    # at 10:00 only the 09:30 bar exists
    p = price_feed.price_at("2024-05-23", "NVDA", datetime(2024, 5, 23, 10, 0), prices_dir=tmp_path)
    assert p == 100.0
    # by 13:00 the 12:00 bar is visible; the 15:30 future bar must NOT leak
    p2 = price_feed.price_at("2024-05-23", "NVDA", datetime(2024, 5, 23, 13, 0), prices_dir=tmp_path)
    assert p2 == 105.0


def test_datasets_endpoint_lists_ready_day(tmp_path):
    price_feed.clear_cache()
    PriceIngester(fetch=_fake_fetch(tmp_path), prices_dir=tmp_path).ingest("2024-05-23", ["NVDA"])
    with TestClient(app) as client:
        days = client.get("/datasets").json()
    found = [d for d in days if d["replay_date"] == "2024-05-23"]
    assert found and "NVDA" in found[0]["tickers"] and "SPY" in found[0]["tickers"]

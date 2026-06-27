from datetime import datetime

import pandas as pd

from app.data import price_feed
from app.data.catalog import record_asset
from app.data.dataset_stats import filing_counts, ticker_stats
from app.data.prices import PriceIngester
from app.db import SessionLocal
from app.models.corpus import Chunk, Document

DATE = "2025-05-29"


def _doc(ticker, when: datetime, n_chunks: int):
    ts = when.timestamp()
    with SessionLocal() as s:
        doc_id = f"{ticker}-{when.date()}"
        s.add(Document(id=doc_id, ticker=ticker, form_type="8-K", source_url="u",
                       published_date=when.isoformat(), published_ts=ts,
                       content_hash=doc_id))
        for i in range(n_chunks):
            s.add(Chunk(id=f"{doc_id}:{i}", document_id=doc_id, ticker=ticker, ordinal=i,
                        text="x", token_count=1, published_ts=ts))
        s.commit()


def _seed_docs():
    _doc("NVDA", datetime(2025, 5, 29, 10, 0), n_chunks=3)   # current day
    _doc("NVDA", datetime(2025, 5, 26, 10, 0), n_chunks=2)   # prior 7d
    _doc("NVDA", datetime(2025, 4, 1, 10, 0), n_chunks=5)    # older


def test_filing_and_chunk_counts_bucket_correctly():
    _seed_docs()
    with SessionLocal() as s:
        c = filing_counts(s, "NVDA", DATE)
    assert c["filings"] == {"current_day": 1, "prior_7d": 1, "older": 1, "total": 3}
    assert c["chunks"] == {"current_day": 3, "prior_7d": 2, "total": 10}


def _ingest_prices(tmp_path, monkeypatch):
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)

    def fetch(t, s, e, i):
        return pd.DataFrame({
            "ts": [datetime(2025, 5, 28, 15, 30),   # lookback bar
                   datetime(2025, 5, 29, 9, 30),
                   datetime(2025, 5, 29, 10, 30),
                   datetime(2025, 5, 29, 11, 30)],  # 3 current-day bars
            "open": [1, 1, 1, 1], "high": [1, 1, 1, 1], "low": [1, 1, 1, 1],
            "close": [1.0, 1.0, 1.0, 1.0], "volume": [1, 1, 1, 1],
        })
    PriceIngester(fetch=fetch, prices_dir=tmp_path).ingest(DATE, ["NVDA"])


def test_price_detail_splits_current_day_from_lookback(tmp_path, monkeypatch):
    _ingest_prices(tmp_path, monkeypatch)
    with SessionLocal() as s:
        st = ticker_stats(s, DATE, "NVDA")
    p = st["prices"]
    assert p["status"] == "READY"
    assert p["n_bars"] == 4
    assert p["n_bars_current_day"] == 3
    assert p["n_bars_lookback"] == 1
    assert p["interval"]  # adaptive interval recorded


def test_warnings_flag_missing_data(tmp_path, monkeypatch):
    _ingest_prices(tmp_path, monkeypatch)  # prices READY, no corpus, no filings
    with SessionLocal() as s:
        st = ticker_stats(s, DATE, "NVDA")
    assert "corpus not ready (missing)" in st["warnings"]
    assert any("no filings" in w for w in st["warnings"])

    # now make it complete -> no warnings
    _seed_docs()
    record_asset(DATE, "NVDA", "CORPUS", "READY", {"n_docs": 3})
    with SessionLocal() as s:
        st2 = ticker_stats(s, DATE, "NVDA")
    assert st2["warnings"] == []


def test_datasets_endpoint_includes_stats(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app

    _ingest_prices(tmp_path, monkeypatch)
    _seed_docs()
    record_asset(DATE, "NVDA", "CORPUS", "READY", {"n_docs": 3})

    client = TestClient(create_app())
    days = client.get("/datasets").json()
    day = next(d for d in days if d["replay_date"] == DATE)
    nvda = next(s for s in day["stats"] if s["ticker"] == "NVDA")
    assert nvda["filings"]["current_day"] == 1
    assert nvda["chunks"]["total"] == 10
    assert nvda["prices"]["n_bars_current_day"] == 3

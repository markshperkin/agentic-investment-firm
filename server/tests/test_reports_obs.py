from datetime import datetime

import pandas as pd

from app.data import price_feed
from app.data.prices import PriceIngester
from app.firm import memory
from app.obs.spans import set_tick, start_run
from app.reports.builder import build_report
from app.reports.excel import report_to_xlsx
from app.agents.reporting import deterministic_summary
from app.state.broker import PaperBroker


def _prices(tmp_path, close_nvda=105.0):
    def fetch(t, s, e, i):
        close = close_nvda if t == "NVDA" else 100.0
        return pd.DataFrame({"ts": [datetime(2024, 5, 23, 9, 30), datetime(2024, 5, 23, 15, 30)],
                             "open": [100, close], "high": [close + 1, close + 1],
                             "low": [99, close - 1], "close": [100.0, close], "volume": [1000, 900]})
    PriceIngester(fetch=fetch, prices_dir=tmp_path).ingest("2024-05-23", ["NVDA"])


def _seed_run(tmp_path, monkeypatch):
    price_feed.clear_cache()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    _prices(tmp_path)
    run_id = start_run("replay", replay_date="2024-05-23")
    set_tick(0, "2024-05-23T10:00:00")
    PaperBroker().execute(ticker="NVDA", side="BUY", quantity=50, reference_price=100.0,
                          as_of=datetime(2024, 5, 23, 10, 0))
    memory.record(run_id=run_id, ticker="NVDA", tick_seq=0, as_of="2024-05-23T10:00:00",
                  stance="BULLISH", confidence=0.8,
                  current_view={"ticker": "NVDA", "stance": "BULLISH", "confidence": 0.8,
                                "key_points": [{"text": "rev 22.6 billion",
                                                "citation": {"chunk_id": "d:0", "source": "8-K"}}]},
                  open_thesis="datacenter growth", position_qty=50, cost_basis=100.0,
                  last_decision_price=100.0, processed_doc_ids=["d"],
                  decision_log=[{"action": "auto_executed"}], dispatch_path="CONTEXT_BUILD")
    return run_id


def test_build_report_pulls_numbers_from_store(tmp_path, monkeypatch):
    run_id = _seed_run(tmp_path, monkeypatch)
    rep = build_report(run_id)
    m = rep["metrics"]
    # mark 105, 50 shares -> holdings 5250; cash dropped by ~5000+commission
    assert m["holdings_value"] == 50 * 105.0
    assert m["benchmark"] == "SPY"
    assert m["benchmark_return"] is not None  # SPY parquet present
    assert m["alpha"] is not None
    assert m["n_trades"] == 1
    assert rep["decisions"][0]["citations"][0]["chunk_id"] == "d:0"
    assert rep["holdings"][0]["unrealized_pnl"] > 0


def test_report_xlsx_is_valid_workbook(tmp_path, monkeypatch):
    run_id = _seed_run(tmp_path, monkeypatch)
    rep = build_report(run_id)
    xlsx = report_to_xlsx(rep, deterministic_summary(rep).model_dump())
    assert xlsx[:2] == b"PK"  # xlsx is a zip
    assert len(xlsx) > 1000


def test_belief_timeline_and_cost_and_export(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app

    run_id = _seed_run(tmp_path, monkeypatch)
    client = TestClient(create_app())

    beliefs = client.get(f"/runs/{run_id}/tickers/NVDA/memory").json()
    assert beliefs and beliefs[0]["stance"] == "BULLISH"

    cost = client.get(f"/runs/{run_id}/cost").json()
    assert "total" in cost and cost["total"]["cost_usd"] >= 0.0

    exp = client.get(f"/runs/{run_id}/export")
    assert exp.status_code == 200
    assert "execute:BUY:NVDA" in exp.text


def test_admin_reset_requires_confirm(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import create_app

    _seed_run(tmp_path, monkeypatch)
    client = TestClient(create_app())

    assert client.post("/admin/reset", json={"confirm": False}).status_code == 400
    res = client.post("/admin/reset", json={"confirm": True})
    assert res.status_code == 200
    assert res.json()["status"] == "reset"
    assert client.get("/runs").json() == []


def test_admin_reset_drops_datasets(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.data.catalog import record_asset
    from app.db import SessionLocal
    from app.main import create_app
    from app.models.corpus import Chunk, Document

    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    _prices(tmp_path)  # writes a PRICES parquet + DataAsset
    with SessionLocal() as s:
        s.add(Document(id="d", ticker="NVDA", form_type="8-K", source_url="u",
                       published_date="2024-05-23", published_ts=1.0, content_hash="h"))
        s.add(Chunk(id="d:0", document_id="d", ticker="NVDA", ordinal=0, text="x",
                    token_count=1, published_ts=1.0))
        s.commit()
    record_asset("2024-05-23", "NVDA", "CORPUS", "READY", {"n_docs": 1})

    client = TestClient(create_app())
    res = client.post("/admin/reset", json={"confirm": True, "drop_corpus": True, "drop_prices": True})
    assert res.status_code == 200

    with SessionLocal() as s:
        assert s.query(Document).count() == 0
        assert s.query(Chunk).count() == 0
    assert client.get("/datasets").json() == []        # prices catalog gone
    assert not (tmp_path / "2024-05-23").exists()       # parquet files gone

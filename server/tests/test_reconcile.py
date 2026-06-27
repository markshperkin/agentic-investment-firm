from datetime import datetime

import pandas as pd

from app.data import price_feed
from app.data.prices import PriceIngester
from app.db import SessionLocal
from app.models.approval import ApprovalRequest
from app.obs.spans import set_tick, start_run
from app.state.broker import PaperBroker
from app.state.portfolio import account_snapshot
from app.state.reconcile import reconcile_on_boot, verify_invariant


def _prices(tmp_path):
    def fetch(t, s, e, i):
        return pd.DataFrame({"ts": [datetime(2024, 5, 23, 9, 30)], "open": [100], "high": [101],
                             "low": [99], "close": [100.0], "volume": [1000]})
    PriceIngester(fetch=fetch, prices_dir=tmp_path).ingest("2024-05-23", ["NVDA"])


def _approved_but_unfilled(approval_id):
    with SessionLocal() as s:
        s.add(ApprovalRequest(
            id=approval_id, run_id="r", ticker="NVDA", side="BUY", quantity=100,
            reference_price=100.0, est_notional=10000.0, as_of="2024-05-23T10:00:00",
            status="APPROVED", decision="approve", approver="mark", trade_id=None,
        ))
        s.commit()


def test_invariant_holds_after_normal_fill(tmp_path, monkeypatch):
    start_run("t")
    set_tick(0)
    price_feed.clear_cache()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    PaperBroker().execute(ticker="NVDA", side="BUY", quantity=10, reference_price=100.0,
                          as_of=datetime(2024, 5, 23, 10, 0))
    inv = verify_invariant()
    assert inv["ok"], inv


def test_reconcile_fills_approved_but_unfilled(tmp_path, monkeypatch):
    start_run("t")
    set_tick(0)
    price_feed.clear_cache()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    _approved_but_unfilled("appr-1")

    out = reconcile_on_boot()
    assert len(out["reconciled"]) == 1
    assert out["reconciled"][0]["status"] == "FILLED"
    assert out["invariant"]["ok"], out["invariant"]
    # the fill lands in the approval's own run book ("r")
    assert account_snapshot("NVDA", 100.0, run_id="r")["position_qty"] == 100

    # idempotent: a second boot does not double-fill
    again = reconcile_on_boot()
    assert account_snapshot("NVDA", 100.0, run_id="r")["position_qty"] == 100
    assert again["invariant"]["ok"]

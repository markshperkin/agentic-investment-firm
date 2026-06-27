from datetime import datetime

import pandas as pd

from app.data import price_feed
from app.data.prices import PriceIngester
from app.firm import clock
from app.firm.dispatcher import decide
from app.firm.runner import run_replay
from app.obs.spans import set_tick


def test_clock_steps_open_to_close_hourly():
    t = clock.ticks("2024-05-23", 60)
    assert t[0] == datetime(2024, 5, 23, 9, 30)
    assert t[-1] == datetime(2024, 5, 23, 16, 0)   # always closes on the bell
    assert len(t) == 8


def test_dispatch_routing():
    assert decide(tick_index=0, n_ticks=7, max_abs_move=0.0, threshold=0.02).path == "CONTEXT_BUILD"
    assert decide(tick_index=6, n_ticks=7, max_abs_move=0.0, threshold=0.02).path == "DAY_REVIEW"
    assert decide(tick_index=3, n_ticks=7, max_abs_move=0.05, threshold=0.02).path == "PRICE_REEVAL"
    assert decide(tick_index=3, n_ticks=7, max_abs_move=0.0, threshold=0.02).path == "SKIP"


def _fixture_prices(tmp_path):
    def fetch(ticker, start, end, interval):
        return pd.DataFrame(
            {
                "ts": [datetime(2024, 5, 23, 9, 30), datetime(2024, 5, 23, 15, 30)],
                "open": [100, 101], "high": [101, 102], "low": [99, 100],
                "close": [100.0, 100.5], "volume": [1000, 900],
            }
        )

    return fetch


def test_run_replay_emits_tick_spans(tmp_path):
    price_feed.clear_cache()
    set_tick(None)
    PriceIngester(fetch=_fixture_prices(tmp_path), prices_dir=tmp_path).ingest("2024-05-23", ["NVDA"])

    import app.data.price_feed as pf

    orig = pf.PRICES_DIR
    pf.PRICES_DIR = tmp_path
    try:
        run_id = run_replay("2024-05-23", ["NVDA"], block_on_approval=False)
    finally:
        pf.PRICES_DIR = orig

    from app.db import SessionLocal
    from app.models.span import Span

    with SessionLocal() as s:
        ticks = s.query(Span).filter(Span.run_id == run_id, Span.kind == "TICK").all()
    paths = [t.name for t in ticks]
    assert paths[0] == "CONTEXT_BUILD"
    assert paths[-1] == "REPORT"        # concluding end-of-day report step
    assert paths[-2] == "DAY_REVIEW"
    assert len(paths) == 9              # 8 clock ticks (incl. the close) + the report step

from datetime import datetime

import pandas as pd

from app.agents.research import ResearchAgent
from app.agents.schemas import ResearchView
from app.data import price_feed
from app.llm.base import ProviderResult
from app.llm.router import LLMRouter


def _write_parquet(tmp_path, rows):
    df = pd.DataFrame(rows)
    out = tmp_path / "2024-05-23"
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "NVDA.parquet", index=False)


# Bars span TWO days: a prior-day bar (the 7-day price lookback) + intraday bars.
# The prior-day bar must NOT count toward "how much did it move today".
LOOKBACK_ROWS = [
    {"ts": datetime(2024, 5, 22, 15, 30), "open": 80, "high": 81, "low": 79, "close": 80.0, "volume": 1},
    {"ts": datetime(2024, 5, 23, 9, 30),  "open": 100, "high": 101, "low": 99, "close": 100.0, "volume": 1},
    {"ts": datetime(2024, 5, 23, 10, 30), "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1},
    {"ts": datetime(2024, 5, 23, 11, 30), "open": 100, "high": 104, "low": 99, "close": 103.0, "volume": 1},
]


def test_pct_change_is_since_open_not_file_start(tmp_path, monkeypatch):
    price_feed.clear_cache()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    _write_parquet(tmp_path, LOOKBACK_ROWS)

    # at 10:30: 100 -> 100.5 since the 09:30 open = +0.5%  (NOT +25% vs the 80 lookback bar)
    f = price_feed.price_features("2024-05-23", "NVDA", datetime(2024, 5, 23, 10, 30))
    assert f["day_open"] == 100.0
    assert abs(f["pct_change"] - 0.005) < 1e-6


def test_move_since_is_tick_over_tick(tmp_path, monkeypatch):
    price_feed.clear_cache()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    _write_parquet(tmp_path, LOOKBACK_ROWS)

    # 10:30 -> 11:30 : 100.5 -> 103.0 = +2.49% (a fresh, single-tick move)
    m = price_feed.move_since("2024-05-23", "NVDA",
                              datetime(2024, 5, 23, 10, 30), datetime(2024, 5, 23, 11, 30))
    assert abs(m - (103.0 - 100.5) / 100.5) < 1e-6
    # first tick has no previous price
    assert price_feed.move_since("2024-05-23", "NVDA", None, datetime(2024, 5, 23, 9, 30)) is None


def test_dispatch_uses_tick_over_tick(tmp_path, monkeypatch):
    """A day that drifts only fractionally each hour must SKIP, even though its
    cumulative move from the file's first bar is huge."""
    from app.firm.runner import _max_abs_move

    price_feed.clear_cache()
    monkeypatch.setattr(price_feed, "PRICES_DIR", tmp_path)
    _write_parquet(tmp_path, LOOKBACK_ROWS)

    # 09:30 -> 10:30 is +0.5% (below 2%) despite +25% vs the lookback bar
    move = _max_abs_move("2024-05-23", ["NVDA"], datetime(2024, 5, 23, 10, 30),
                         datetime(2024, 5, 23, 9, 30))
    assert move < 0.02
    # 10:30 -> 11:30 is +2.49% (above 2%) -> would route PRICE_REEVAL
    move2 = _max_abs_move("2024-05-23", ["NVDA"], datetime(2024, 5, 23, 11, 30),
                          datetime(2024, 5, 23, 10, 30))
    assert move2 >= 0.02


class _Recorder:
    def __init__(self):
        self.prompts = []

    def complete(self, model, system, prompt, schema):
        self.prompts.append(prompt)
        return ProviderResult(
            data={"ticker": "NVDA", "stance": "BULLISH", "confidence": 0.8, "key_points": []},
            prompt_tokens=1, completion_tokens=1,
        )


def test_prior_thesis_is_pushed_into_research():
    prior = ResearchView(ticker="NVDA", stance="NEUTRAL", confidence=0.4, key_points=[])
    rec = _Recorder()
    ResearchAgent(LLMRouter(provider=rec)).analyze(
        "NVDA", datetime(2024, 5, 23, 11, 0), chunks=[], prior_view=prior,
    )
    assert rec.prompts, "research was not called"
    assert "Prior view (carried forward): stance NEUTRAL" in rec.prompts[0]

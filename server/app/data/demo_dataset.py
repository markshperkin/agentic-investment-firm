"""Demo dataset: a scripted single-day NVDA replay that exercises every dispatch
path in one run.

Real SEC EDGAR filings drive the open thesis (the ~$85k HITL buy at the open); a
fabricated price curve plus five fabricated articles drive the intraday and
end-of-day paths. The curve deliberately **overshoots** the firm's bound caps
(stop 4% / target 10%) so the deterministic stop/target exits fire regardless of
the exact exit bounds the live PM picks.

Hourly ticks 09:30..16:00 (8 ticks, the default clock):

  T0 09:30  CONTEXT_BUILD      real 8-K -> BUY ~$85k -> HITL approve
  T1 10:30  MONITOR_SELL       +10.5% -> TAKE_PROFIT
  T2 11:30  INCREMENTAL_NEWS   bullish article -> re-buy
  T3 12:30  MONITOR_SELL       -4.7% vs basis -> STOP_LOSS
  T4 13:30  INCREMENTAL_NEWS   bullish article -> re-buy
  T5 14:30  INCREMENTAL_NEWS   bearish article -> PM SELL (mid-day, in-band)
  T6 15:30  INCREMENTAL_NEWS   bullish article -> re-buy, hold
  T7 16:00  DAY_REVIEW         bearish/gap article -> FLATTEN
"""
from datetime import datetime

import pandas as pd

from app.rag.edgar import FakeFilingSource, RawFiling

DEMO_DATE = "2026-05-29"
TICKER = "NVDA"

# (tick HH:MM, NVDA close, SPY close). NVDA close drives every trigger; SPY is the
# (flat) benchmark. Overshoot: T1 clears the 10% target cap, T3 clears the 4% stop cap.
_CURVE: list[tuple[str, float, float]] = [
    ("09:30", 100.0, 500.0),   # T0 entry basis ~100
    ("10:30", 110.5, 500.2),   # T1 take-profit  (+10.5%)
    ("11:30", 107.0, 500.4),   # T2 re-buy       basis ~107
    ("12:30", 102.0, 500.6),   # T3 stop-loss    (-4.7% vs 107)
    ("13:30", 104.0, 500.8),   # T4 re-buy       basis ~104
    ("14:30", 101.0, 501.0),   # T5 news-sell    (in-band: above the 4% stop)
    ("15:30", 102.0, 501.2),   # T6 re-buy       basis ~102
    ("16:00", 102.5, 501.5),   # T7 flatten      (in-band)
]


def _ts(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{DEMO_DATE}T{hhmm}:00")


def demo_price_fetch(ticker: str, start, end, interval) -> pd.DataFrame:
    """Drop-in `PriceIngester.fetch` that returns the scripted candles instead of
    hitting yfinance. Close = the scripted level; high/low are thin wicks around it
    (only close drives the trigger scans)."""
    col = 1 if ticker != "SPY" else 2
    rows = []
    for entry in _CURVE:
        hhmm, c = entry[0], entry[col]
        rows.append({
            "ts": _ts(hhmm), "open": float(c), "high": round(c * 1.003, 4),
            "low": round(c * 0.997, 4), "close": float(c), "volume": 1_000_000,
        })
    return pd.DataFrame(rows)


# Five fabricated articles, timestamped to land on specific ticks. #3 and #5 are the
# load-bearing bearish ones — they drive the mid-day news-sell and the EOD flatten.
DEMO_ARTICLES: list[RawFiling] = [
    RawFiling(TICKER, "NEWS", "https://demo.local/nvda/blackwell-supply", _ts("11:30"),
              "NVIDIA Secures Multi-Year Blackwell Supply Deal With Top Hyperscaler. "
              "NVIDIA has signed a multi-year agreement to supply next-generation Blackwell "
              "GPUs to a top-three cloud provider, a deal expected to add materially to "
              "data-center revenue beginning next quarter. Analysts called the agreement a "
              "strong incremental demand signal that reinforces NVIDIA's data-center backlog "
              "and pricing power."),
    RawFiling(TICKER, "NEWS", "https://demo.local/nvda/capacity-guidance", _ts("13:30"),
              "NVIDIA Lifts Data-Center Capacity Guidance on Surging AI Orders. "
              "NVIDIA said it is expanding production capacity to meet stronger-than-expected "
              "orders for its AI accelerators, citing a robust backlog and reiterating "
              "confidence in sustained data-center growth through the year. Management "
              "characterized demand as broad-based across cloud and enterprise customers."),
    RawFiling(TICKER, "NEWS", "https://demo.local/nvda/export-curbs", _ts("14:30"),
              "Report: Fresh U.S. Export Curbs Could Sharply Curtail NVIDIA China Sales. "
              "A regulatory report indicates U.S. authorities are preparing tightened export "
              "controls that would restrict NVIDIA's advanced-chip sales to China, a market "
              "that represents a meaningful share of data-center revenue. Desks warned the "
              "measure could force NVIDIA to write down China-bound inventory and cut "
              "near-term guidance, and the shares came under immediate pressure."),
    RawFiling(TICKER, "NEWS", "https://demo.local/nvda/inference-platform", _ts("15:30"),
              "Export-Restriction Fears Look Overblown: NVIDIA Reaffirms Limited China Exposure "
              "and Launches Next-Generation Inference Platform. NVIDIA pushed back hard on the "
              "day's report of potential U.S. export restrictions, telling investors its China "
              "data-center exposure is limited and already largely de-risked and that the "
              "proposed measures would not materially affect its outlook or guidance. At the same "
              "event the company unveiled a next-generation inference platform, with several "
              "marquee customers committing to early adoption, a launch analysts said reinforces "
              "NVIDIA's data-center moat and broadens demand well beyond model training. The "
              "update reversed the earlier concern and refocused the market on accelerating AI "
              "infrastructure demand; the bullish thesis is firmly intact."),
    RawFiling(TICKER, "NEWS", "https://demo.local/nvda/overnight-gap", _ts("16:00"),
              "NVIDIA Faces Elevated Overnight Gap Risk; Desks Cut Exposure Into the Close. "
              "Strategists warned of elevated overnight gap risk for high-beta semiconductor "
              "names including NVIDIA, with key Federal Reserve commentary and still-unresolved "
              "U.S.-China export headlines due after the close. Several desks said they were "
              "reducing exposure into the bell to avoid an unhedged overnight gap in the name."),
]


# Canned bullish entry filing — used for OFFLINE validation only (the live ingest
# pulls the real EDGAR 8-K instead). Timestamped pre-open so CONTEXT_BUILD sees it.
DEMO_ENTRY_8K = RawFiling(
    TICKER, "8-K", "https://demo.local/nvda/q1-earnings", _ts("06:30"),
    "NVIDIA Reports Record Quarterly Revenue, Raises Outlook. NVIDIA reported record "
    "data-center revenue for the quarter, well ahead of consensus, driven by surging demand "
    "for its AI accelerators. The company raised its forward outlook, citing a multi-quarter "
    "backlog and expanding gross margins. Management described demand visibility as the "
    "strongest in the company's history.")


def ingest_demo() -> dict:
    """Build the demo dataset end to end: scripted prices over the real SEC EDGAR
    filings, plus the five fabricated articles injected into the same vector store.

    Intended to run live (real EDGAR pull + Voyage embeddings). The scripted price
    curve overrides yfinance for the day; EDGAR is best-effort so a network hiccup
    degrades to articles-only rather than failing the whole ingest."""
    from app.data.prices import PriceIngester
    from app.rag.factory import get_corpus_ingester, get_embedder, get_store
    from app.rag.ingest import CorpusIngester

    prices = PriceIngester(fetch=demo_price_fetch).ingest(DEMO_DATE, [TICKER])

    try:
        corpus = get_corpus_ingester().ingest(DEMO_DATE, [TICKER])
    except Exception as exc:  # noqa: BLE001  live-only EDGAR/Voyage path
        corpus = {TICKER: f"FAILED: {exc}"}

    articles = CorpusIngester(
        FakeFilingSource(DEMO_ARTICLES), get_embedder(), get_store()
    ).ingest(DEMO_DATE, [TICKER])

    return {"date": DEMO_DATE, "tickers": [TICKER], "prices": prices,
            "corpus": corpus, "articles": articles}

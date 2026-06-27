from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.corpus import Chunk, Document
from app.models.dataset import DataAsset

LOOKBACK_DAYS = 7


def _bounds(replay_date: str) -> tuple[float, float, float]:
    """Epoch bounds: prior-7d start, current-day start, current-day end (exclusive)."""
    day_start = datetime.fromisoformat(replay_date).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        (day_start - timedelta(days=LOOKBACK_DAYS)).timestamp(),
        day_start.timestamp(),
        (day_start + timedelta(days=1)).timestamp(),
    )


def _count(session: Session, model, ticker: str, lo: float, hi: float) -> int:
    return session.execute(
        select(func.count()).select_from(model).where(
            model.ticker == ticker, model.published_ts >= lo, model.published_ts < hi,
        )
    ).scalar_one()


def _total(session: Session, model, ticker: str) -> int:
    return session.execute(
        select(func.count()).select_from(model).where(model.ticker == ticker)
    ).scalar_one()


def filing_counts(session: Session, ticker: str, replay_date: str) -> dict:
    """Filings and embedded chunks for `ticker`, bucketed by publication time relative
    to the replay day: current day, the prior 7 days, everything older, and totals."""
    prior_lo, day_lo, day_hi = _bounds(replay_date)
    docs_current = _count(session, Document, ticker, day_lo, day_hi)
    docs_prior = _count(session, Document, ticker, prior_lo, day_lo)
    docs_total = _total(session, Document, ticker)
    chunks_current = _count(session, Chunk, ticker, day_lo, day_hi)
    chunks_prior = _count(session, Chunk, ticker, prior_lo, day_lo)
    chunks_total = _total(session, Chunk, ticker)
    return {
        "filings": {
            "current_day": docs_current,
            "prior_7d": docs_prior,
            "older": max(docs_total - docs_current - docs_prior, 0),
            "total": docs_total,
        },
        "chunks": {
            "current_day": chunks_current,
            "prior_7d": chunks_prior,
            "total": chunks_total,
        },
    }


def _asset(session: Session, replay_date: str, ticker: str, kind: str) -> DataAsset | None:
    return session.execute(
        select(DataAsset).where(
            DataAsset.replay_date == replay_date,
            DataAsset.ticker == ticker,
            DataAsset.kind == kind,
        )
    ).scalar_one_or_none()


def _warnings(prices_status: str, prices: dict, corpus_status: str, counts: dict) -> list[str]:
    w: list[str] = []
    if prices_status != "READY":
        w.append(f"prices not ready ({prices_status.lower()})")
    elif prices.get("n_bars", 0) == 0:
        w.append("no price bars stored")
    elif prices.get("n_bars_current_day", 0) == 0:
        w.append("no intraday bars on the replay day")
    if corpus_status != "READY":
        w.append(f"corpus not ready ({corpus_status.lower()})")
    f = counts["filings"]
    if f["current_day"] == 0 and f["prior_7d"] == 0:
        w.append("no filings in the last 7 days to ground on")
    return w


def ticker_stats(session: Session, replay_date: str, ticker: str) -> dict:
    """Full per-ticker completeness picture for the Datasets tab."""
    counts = filing_counts(session, ticker, replay_date)
    prices_asset = _asset(session, replay_date, ticker, "PRICES")
    corpus_asset = _asset(session, replay_date, ticker, "CORPUS")
    prices_status = prices_asset.status if prices_asset else "MISSING"
    corpus_status = corpus_asset.status if corpus_asset else "MISSING"
    prices = prices_asset.detail_json or {} if prices_asset else {}
    return {
        "ticker": ticker,
        "prices": {"status": prices_status, **prices},
        "corpus_status": corpus_status,
        "filings": counts["filings"],
        "chunks": counts["chunks"],
        "warnings": _warnings(prices_status, prices, corpus_status, counts),
    }

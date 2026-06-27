from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.data.catalog import ready_days
from app.data.dataset_stats import ticker_stats
from app.data.prices import PriceIngester
from app.db import get_session

router = APIRouter()


class IngestRequest(BaseModel):
    date: str
    tickers: list[str]


@router.get("/datasets")
def datasets(session: Session = Depends(get_session)) -> list[dict]:
    # Each runnable day carries a per-ticker completeness block: filings + embedded
    # chunks bucketed (current-day vs prior-7d), price candles, and validation warnings.
    days = ready_days(session, required_kinds=("PRICES",))
    return [
        {
            "replay_date": d["replay_date"],
            "tickers": d["tickers"],
            "stats": [ticker_stats(session, d["replay_date"], t) for t in d["tickers"]],
        }
        for d in days
    ]


@router.post("/datasets")
def ingest(req: IngestRequest) -> dict:
    prices = PriceIngester().ingest(req.date, req.tickers)
    try:
        from app.rag.factory import get_corpus_ingester

        corpus = get_corpus_ingester().ingest(req.date, req.tickers)
    except Exception as exc:  # noqa: BLE001  live-only path (EDGAR/Voyage/Chroma)
        corpus = {"error": str(exc)}
    return {"date": req.date, "prices": prices, "corpus": corpus}


@router.post("/datasets/demo")
def ingest_demo_dataset() -> dict:
    """One-click demo dataset: scripted NVDA prices + real EDGAR filings + the
    fabricated articles, engineered so a single replay fires every dispatch path."""
    from app.data.demo_dataset import ingest_demo

    return ingest_demo()

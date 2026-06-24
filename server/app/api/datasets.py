from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.data.catalog import ready_days
from app.data.prices import PriceIngester
from app.db import get_session

router = APIRouter()


class IngestRequest(BaseModel):
    date: str
    tickers: list[str]


@router.get("/datasets")
def datasets(session: Session = Depends(get_session)) -> list[dict]:
    # A day is runnable once both PRICES and CORPUS are READY (CORPUS lands in T09).
    return ready_days(session, required_kinds=("PRICES",))


@router.post("/datasets")
def ingest(req: IngestRequest) -> dict:
    prices = PriceIngester().ingest(req.date, req.tickers)
    try:
        from app.rag.factory import get_corpus_ingester

        corpus = get_corpus_ingester().ingest(req.date, req.tickers)
    except Exception as exc:  # noqa: BLE001  live-only path (EDGAR/Voyage/Chroma)
        corpus = {"error": str(exc)}
    return {"date": req.date, "prices": prices, "corpus": corpus}

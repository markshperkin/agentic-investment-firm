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
    results = PriceIngester().ingest(req.date, req.tickers)
    return {"date": req.date, "prices": results}

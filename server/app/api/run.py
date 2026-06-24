from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.data.catalog import ready_days
from app.db import SessionLocal
from app.firm.runner import run_replay

router = APIRouter()


class ReplayRequest(BaseModel):
    date: str
    tickers: list[str]


@router.post("/run/replay")
def replay(req: ReplayRequest) -> dict:
    with SessionLocal() as s:
        ready = {d["replay_date"]: d["tickers"] for d in ready_days(s, required_kinds=("PRICES",))}
    if req.date not in ready:
        raise HTTPException(
            status_code=409,
            detail=f"No dataset for {req.date}. Ingest it first via POST /datasets.",
        )
    run_id = run_replay(req.date, req.tickers)
    return {"run_id": run_id, "date": req.date}

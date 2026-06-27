import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.data.catalog import ready_days
from app.db import SessionLocal
from app.firm.runner import run_replay
from app.obs.spans import end_run, start_run
from app.rag.integrity import CorpusCorrupted, ensure_corpus_ready

router = APIRouter()


class ReplayRequest(BaseModel):
    date: str
    tickers: list[str]


def _run_background(run_id: str, date: str, tickers: list[str]) -> None:
    try:
        run_replay(date, tickers, block_on_approval=True, run_id=run_id)
    except Exception:  # noqa: BLE001  background thread — never let it die silently
        end_run(run_id, status="ERROR")


@router.post("/run/replay")
def replay(req: ReplayRequest) -> dict:
    with SessionLocal() as s:
        ready = {d["replay_date"]: d["tickers"] for d in ready_days(s, required_kinds=("PRICES",))}
    if req.date not in ready:
        raise HTTPException(
            status_code=409,
            detail=f"No dataset for {req.date}. Ingest it first via POST /datasets.",
        )
    # Data-integrity preflight: stop on a corrupted (missing) SQL corpus; transparently
    # embed + backfill the vector store if SQL has the corpus but the vectors are gone.
    try:
        corpus = ensure_corpus_ready(req.tickers)
    except CorpusCorrupted as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:  # noqa: BLE001  embedding/store failure -> surface, don't start
        raise HTTPException(status_code=503, detail=f"vector store backfill failed: {exc}")
    # Create the run row up front so we can return its id immediately, then drive the
    # replay in a background thread — the run pauses at human-approval gates without
    # holding the HTTP request open. The feed streams progress over WS /stream.
    run_id = start_run(kind="replay", replay_date=req.date)
    threading.Thread(target=_run_background, args=(run_id, req.date, req.tickers),
                     daemon=True).start()
    return {"run_id": run_id, "date": req.date, "corpus": corpus}

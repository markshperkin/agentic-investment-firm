import shutil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.data import price_feed
from app.db import SessionLocal
from app.models.approval import ApprovalRequest
from app.models.corpus import Chunk, Document
from app.models.dataset import DataAsset
from app.models.portfolio import Portfolio, Position, Trade
from app.models.span import Run, Span
from app.models.ticker_memory import TickerMemory

router = APIRouter()

# Trade/observability state. Always cleared on a reset.
_STORE = [Span, Run, TickerMemory, ApprovalRequest, Trade, Position, Portfolio]


class ResetRequest(BaseModel):
    confirm: bool = False
    drop_corpus: bool = False   # documents + chunks + CORPUS catalog + vector store
    drop_prices: bool = False   # PRICES catalog + price parquet files


@router.post("/admin/reset")
def reset(req: ResetRequest) -> dict:
    if not req.confirm:
        raise HTTPException(400, "reset requires confirm=true")
    cleared: dict[str, int] = {}
    with SessionLocal() as s:
        for model in _STORE:
            cleared[model.__tablename__] = s.query(model).delete()
        if req.drop_corpus:
            cleared["documents"] = s.query(Document).delete()
            cleared["chunks"] = s.query(Chunk).delete()
            cleared["data_assets(corpus)"] = (
                s.query(DataAsset).filter(DataAsset.kind == "CORPUS").delete()
            )
        if req.drop_prices:
            cleared["data_assets(prices)"] = (
                s.query(DataAsset).filter(DataAsset.kind == "PRICES").delete()
            )
        s.commit()

    if req.drop_corpus:
        _clear_vector_store()
    if req.drop_prices:
        _clear_price_files()
    return {"status": "reset", "cleared": cleared,
            "dropped_corpus": req.drop_corpus, "dropped_prices": req.drop_prices}


def _clear_vector_store() -> None:
    try:
        from app.rag.factory import get_store

        get_store().clear()
    except Exception:  # noqa: BLE001  store may be unavailable (no chroma installed)
        pass


def _clear_price_files() -> None:
    shutil.rmtree(price_feed.PRICES_DIR, ignore_errors=True)
    price_feed.clear_cache()

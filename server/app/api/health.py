from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_session

router = APIRouter()


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    db_ok = True
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    # The equity invariant (cash + holdings == equity) is enforced once the
    # portfolio store exists (T06); until then it has nothing to check.
    invariant_ok = True

    return {
        "status": "ok" if db_ok and invariant_ok else "degraded",
        "db_ok": db_ok,
        "invariant_ok": invariant_ok,
    }

import json

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.span import Span

router = APIRouter()


@router.get("/runs/{run_id}/export")
def export_jsonl(run_id: str, session: Session = Depends(get_session)) -> Response:
    """The full trace as JSONL — one span per line, time-ordered. This is the
    replay-from-trace artifact: everything the firm did, externally auditable."""
    spans = session.execute(
        select(Span).where(Span.run_id == run_id).order_by(Span.started_at.asc())
    ).scalars().all()
    body = "\n".join(json.dumps(s.as_event(), default=str) for s in spans)
    return Response(
        content=body,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="trace-{run_id[:8]}.jsonl"'},
    )

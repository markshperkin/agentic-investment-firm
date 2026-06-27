from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import select

from app.agents.reporting import deterministic_summary
from app.db import SessionLocal
from app.models.span import Run, Span
from app.reports.builder import build_report
from app.reports.excel import report_to_xlsx

router = APIRouter()


def _stored_narrative(run_id: str) -> dict | None:
    """The narrative written by the run's concluding reporting step, if present."""
    with SessionLocal() as s:
        row = s.execute(
            select(Span)
            .where(Span.run_id == run_id, Span.kind == "AGENT", Span.name == "reporting")
            .order_by(Span.started_at.desc())
        ).scalars().first()
        return row.output_json if row and row.output_json else None


def _summary(report: dict) -> dict:
    # The LLM narrative is written exactly once, as the run's concluding reporting step.
    # Viewing the report NEVER calls the agent: reuse the stored narrative, and for legacy
    # runs that lack one, fall back to the deterministic template (still no LLM call).
    return _stored_narrative(report["run_id"]) or deterministic_summary(report).model_dump()


def _require_run(run_id: str) -> None:
    with SessionLocal() as s:
        if s.get(Run, run_id) is None:
            raise HTTPException(404, f"run {run_id} not found")


@router.get("/runs/{run_id}/report")
def report(run_id: str) -> dict:
    _require_run(run_id)
    rep = build_report(run_id)
    rep["narrative"] = _summary(rep)
    return rep


@router.get("/runs/{run_id}/report.xlsx")
def report_xlsx(run_id: str) -> Response:
    _require_run(run_id)
    rep = build_report(run_id)
    xlsx = report_to_xlsx(rep, _summary(rep))
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="report-{run_id[:8]}.xlsx"'},
    )

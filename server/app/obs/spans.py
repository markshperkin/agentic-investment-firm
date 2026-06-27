import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Callable

from app.db import SessionLocal
from app.models.span import Run, Span

_current_run: ContextVar[str | None] = ContextVar("current_run", default=None)
_current_parent: ContextVar[str | None] = ContextVar("current_parent", default=None)
_current_tick: ContextVar[int | None] = ContextVar("current_tick", default=None)
_current_as_of: ContextVar[str | None] = ContextVar("current_as_of", default=None)

# Subscribers receive each span dict as it is created or updated. Used by the
# live feed (T04) to push events over WebSocket; persistence does not depend on it.
_subscribers: list[Callable[[dict], None]] = []


def subscribe(fn: Callable[[dict], None]) -> None:
    _subscribers.append(fn)


def _notify(event: dict) -> None:
    for fn in list(_subscribers):
        try:
            fn(event)
        except Exception:
            pass


def start_run(kind: str, replay_date: str | None = None) -> str:
    run_id = uuid.uuid4().hex
    with SessionLocal() as s:
        s.add(Run(id=run_id, kind=kind, replay_date=replay_date, status="RUNNING"))
        s.commit()
    _current_run.set(run_id)
    return run_id


def end_run(run_id: str, status: str = "DONE") -> None:
    with SessionLocal() as s:
        run = s.get(Run, run_id)
        if run:
            run.status = status
            run.ended_at = datetime.utcnow()
            s.commit()


def set_tick(tick_seq: int | None, as_of: str | None = None) -> None:
    _current_tick.set(tick_seq)
    _current_as_of.set(as_of)


def set_run(run_id: str) -> None:
    """Bind the current-run contextvar in this thread/task (used when a background
    run continues a run_id created by the request handler)."""
    _current_run.set(run_id)


def current_run() -> str | None:
    """The run bound to this thread/task, if any. Lets the book scope itself to the
    active run without threading run_id through every account call."""
    return _current_run.get()


class SpanHandle:
    def __init__(self, span_id: str):
        self.id = span_id
        self._output: dict | None = None
        self._fields: dict[str, Any] = {}

    def set_output(self, output: dict) -> None:
        self._output = output

    def set(self, **fields: Any) -> None:
        self._fields.update(fields)


@contextmanager
def span(
    kind: str,
    name: str,
    *,
    agent: str | None = None,
    tool: str | None = None,
    ticker: str | None = None,
    trade_id: str | None = None,
    input: dict | None = None,
    run_id: str | None = None,
):
    span_id = uuid.uuid4().hex
    run = run_id or _current_run.get()
    parent = _current_parent.get()
    tick = _current_tick.get()
    as_of = _current_as_of.get()
    started = datetime.utcnow()

    with SessionLocal() as s:
        row = Span(
            id=span_id,
            run_id=run or "",
            parent_span_id=parent,
            tick_seq=tick,
            as_of=as_of,
            kind=kind,
            name=name,
            agent=agent,
            tool=tool,
            ticker=ticker,
            trade_id=trade_id,
            input_json=input,
            status="PENDING",
            started_at=started,
        )
        s.add(row)
        s.commit()
        _notify(row.as_event())

    handle = SpanHandle(span_id)
    token = _current_parent.set(span_id)
    status = "OK"
    error = None
    try:
        yield handle
    except Exception as exc:
        status = "ERROR"
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        _current_parent.reset(token)
        ended = datetime.utcnow()
        latency = int((ended - started).total_seconds() * 1000)
        with SessionLocal() as s:
            row = s.get(Span, span_id)
            if row:
                row.status = handle._fields.pop("status", status)
                row.error = error
                row.ended_at = ended
                row.latency_ms = latency
                if handle._output is not None:
                    row.output_json = handle._output
                for k, v in handle._fields.items():
                    setattr(row, k, v)
                s.commit()
                _notify(row.as_event())

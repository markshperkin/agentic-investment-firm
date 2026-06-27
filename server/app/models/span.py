from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)
    replay_date: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Span(Base):
    __tablename__ = "spans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tick_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    as_of: Mapped[str | None] = mapped_column(String, nullable=True)

    kind: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    agent: Mapped[str | None] = mapped_column(String, nullable=True)
    tool: Mapped[str | None] = mapped_column(String, nullable=True)
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    trade_id: Mapped[str | None] = mapped_column(String, nullable=True)

    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_hit: Mapped[bool | None] = mapped_column(default=None, nullable=True)

    status: Mapped[str] = mapped_column(String, default="PENDING")
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def as_event(self) -> dict:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "parent_span_id": self.parent_span_id,
            "tick_seq": self.tick_seq,
            "as_of": self.as_of,
            "kind": self.kind,
            "name": self.name,
            "agent": self.agent,
            "tool": self.tool,
            "ticker": self.ticker,
            "trade_id": self.trade_id,
            "input": self.input_json,
            "output": self.output_json,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "cache_hit": self.cache_hit,
            "status": self.status,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
        }

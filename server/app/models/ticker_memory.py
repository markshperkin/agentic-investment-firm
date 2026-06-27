from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TickerMemory(Base):
    __tablename__ = "ticker_memory"
    __table_args__ = (UniqueConstraint("run_id", "ticker", "tick_seq", name="uq_memory"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    tick_seq: Mapped[int] = mapped_column(Integer)
    as_of: Mapped[str | None] = mapped_column(String, nullable=True)

    stance: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_view_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    open_thesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    position_qty: Mapped[int] = mapped_column(Integer, default=0)
    cost_basis: Mapped[float] = mapped_column(Float, default=0.0)
    last_decision_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    processed_doc_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    decision_log_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    dispatch_path: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

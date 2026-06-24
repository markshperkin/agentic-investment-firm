from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ApprovalRequest(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    ticker: Mapped[str] = mapped_column(String)
    side: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer)
    reference_price: Mapped[float] = mapped_column(Float)
    est_notional: Mapped[float] = mapped_column(Float)
    as_of: Mapped[str] = mapped_column(String)
    thesis_card_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_reasoning: Mapped[str | None] = mapped_column(String, nullable=True)

    status: Mapped[str] = mapped_column(String, default="PENDING")  # PENDING|APPROVED|REJECTED
    decision: Mapped[str | None] = mapped_column(String, nullable=True)  # approve|edit|reject
    edited_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approver: Mapped[str | None] = mapped_column(String, nullable=True)
    trade_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

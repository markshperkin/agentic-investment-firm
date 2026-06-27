from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Portfolio(Base):
    __tablename__ = "portfolio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    cash: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String, default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(Integer, index=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    avg_cost_basis: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    stop_loss_pct: Mapped[float] = mapped_column(Float, default=0.0)
    take_profit_pct: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String)
    reference_price: Mapped[float] = mapped_column(Float)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    slippage: Mapped[float | None] = mapped_column(Float, nullable=True)
    commission: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    as_of: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    filled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

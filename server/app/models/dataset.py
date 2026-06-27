from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DataAsset(Base):
    __tablename__ = "data_assets"
    __table_args__ = (UniqueConstraint("replay_date", "ticker", "kind", name="uq_asset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    replay_date: Mapped[str] = mapped_column(String, index=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)  # PRICES | CORPUS
    status: Mapped[str] = mapped_column(String)  # READY | INGESTING | FAILED
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

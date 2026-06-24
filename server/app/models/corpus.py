from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    form_type: Mapped[str] = mapped_column(String)
    source_url: Mapped[str] = mapped_column(String)
    published_date: Mapped[str] = mapped_column(String)  # ISO
    published_ts: Mapped[float] = mapped_column(Float, index=True)  # epoch, for range filters
    content_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document_id: Mapped[str] = mapped_column(String, index=True)
    ticker: Mapped[str] = mapped_column(String, index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    published_ts: Mapped[float] = mapped_column(Float, index=True)

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.dataset import DataAsset


def record_asset(replay_date: str, ticker: str, kind: str, status: str, detail: dict | None = None) -> None:
    with SessionLocal() as s:
        existing = s.execute(
            select(DataAsset).where(
                DataAsset.replay_date == replay_date,
                DataAsset.ticker == ticker,
                DataAsset.kind == kind,
            )
        ).scalar_one_or_none()
        if existing:
            existing.status = status
            existing.detail_json = detail
        else:
            s.add(DataAsset(replay_date=replay_date, ticker=ticker, kind=kind,
                            status=status, detail_json=detail))
        s.commit()


def assets_for(session: Session, replay_date: str) -> list[DataAsset]:
    return list(
        session.execute(
            select(DataAsset).where(DataAsset.replay_date == replay_date)
        ).scalars().all()
    )


def ready_days(session: Session, required_kinds: tuple[str, ...] = ("PRICES",)) -> list[dict]:
    """A ticker is ready for a day when every required kind is READY. A day is
    listed with the set of its ready tickers — this is what the run dropdown shows."""
    rows = session.execute(select(DataAsset)).scalars().all()
    by_day_ticker: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rows:
        if r.status == "READY":
            by_day_ticker[(r.replay_date, r.ticker)].add(r.kind)

    days: dict[str, list[str]] = defaultdict(list)
    for (day, ticker), kinds in by_day_ticker.items():
        if all(k in kinds for k in required_kinds):
            days[day].append(ticker)

    return [{"replay_date": d, "tickers": sorted(t)} for d, t in sorted(days.items())]

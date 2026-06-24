from datetime import datetime, time, timedelta

OPEN = time(9, 30)
CLOSE = time(16, 0)


def ticks(replay_date: str, interval_minutes: int = 60) -> list[datetime]:
    """Discrete decision points from open to close on the replay day."""
    day = datetime.fromisoformat(replay_date).date()
    cursor = datetime.combine(day, OPEN)
    end = datetime.combine(day, CLOSE)
    out: list[datetime] = []
    while cursor <= end:
        out.append(cursor)
        cursor += timedelta(minutes=interval_minutes)
    return out

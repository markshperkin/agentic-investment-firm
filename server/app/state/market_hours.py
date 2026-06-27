from datetime import datetime, time

OPEN = time(9, 30)
CLOSE = time(16, 0)


def is_market_open(as_of: datetime) -> bool:
    """Replay timestamps are treated as US/Eastern. Regular session only,
    Monday–Friday 09:30–16:00 (holidays not modeled in V1)."""
    if as_of.weekday() >= 5:
        return False
    return OPEN <= as_of.time() <= CLOSE

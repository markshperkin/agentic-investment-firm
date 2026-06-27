class LookaheadViolation(Exception):
    """Raised when content dated after `as_of` reaches an agent context. Aborts
    the run loudly rather than silently corrupting results with future data."""


def assert_no_lookahead(records: list[dict], as_of_ts: float) -> None:
    """Independent boundary check: enforced on EVERY path, including the ones that
    bypass the retriever (direct news push, cached-view reuse). The retriever also
    filters by published_ts <= as_of — this proves it held."""
    for r in records:
        ts = r.get("published_ts")
        if ts is not None and ts > as_of_ts:
            raise LookaheadViolation(
                f"chunk {r.get('chunk_id')} published_ts={ts} > as_of={as_of_ts}"
            )

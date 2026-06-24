import asyncio

from app.obs.spans import subscribe


class Broadcaster:
    """Fans span events out to connected WebSocket clients. Persistence does not
    depend on this — the feed always re-hydrates from the DB on (re)connect."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def register(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.add(q)
        return q

    def unregister(self, q: asyncio.Queue) -> None:
        self._queues.discard(q)

    def publish(self, event: dict) -> None:
        # Called from the (possibly non-async) firm code; hop to the loop thread.
        if self._loop is None:
            return
        for q in list(self._queues):
            self._loop.call_soon_threadsafe(q.put_nowait, event)


broadcaster = Broadcaster()
subscribe(broadcaster.publish)

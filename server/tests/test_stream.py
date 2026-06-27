import asyncio

from app.obs.stream import Broadcaster


def test_broadcaster_delivers_to_registered_queue():
    loop = asyncio.new_event_loop()
    try:
        b = Broadcaster()
        b.bind_loop(loop)
        q = b.register()
        b.publish({"kind": "EVENT", "name": "ping"})
        loop.run_until_complete(asyncio.sleep(0))
        assert q.get_nowait() == {"kind": "EVENT", "name": "ping"}
    finally:
        loop.close()


def test_unregister_stops_delivery():
    loop = asyncio.new_event_loop()
    try:
        b = Broadcaster()
        b.bind_loop(loop)
        q = b.register()
        b.unregister(q)
        b.publish({"x": 1})
        loop.run_until_complete(asyncio.sleep(0))
        assert q.empty()
    finally:
        loop.close()

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.obs.stream import broadcaster

router = APIRouter()


@router.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    await ws.accept()
    queue = broadcaster.register()
    try:
        while True:
            event = await queue.get()
            await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.unregister(queue)

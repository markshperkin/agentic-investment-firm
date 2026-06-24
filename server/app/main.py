import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import feed, health, stream
from app.config import get_settings
from app.db import init_db
from app.obs.stream import broadcaster


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    broadcaster.bind_loop(asyncio.get_running_loop())
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(feed.router)
    app.include_router(stream.router)

    web_dist = os.environ.get("WEB_DIST", "web_dist")
    if os.path.isdir(web_dist):
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")
    return app


app = create_app()

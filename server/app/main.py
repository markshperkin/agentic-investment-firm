from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import feed, health
from app.config import get_settings
from app.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(health.router)
    app.include_router(feed.router)
    return app


app = create_app()

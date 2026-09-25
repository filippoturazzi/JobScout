"""ASGI application. Run with ``jobscout serve`` or ``uvicorn jobscout.api.app:app``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import Session

from jobscout import __version__
from jobscout.api.routers import jobs, matches, preferences
from jobscout.db import get_engine, init_db
from jobscout.pipeline.users import get_or_create_default_user


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    init_db(engine)
    with Session(engine) as session:
        get_or_create_default_user(session)
    yield


def create_app() -> FastAPI:
    application = FastAPI(title="JobScout", version=__version__, lifespan=lifespan)
    application.include_router(jobs.router)
    application.include_router(matches.router)
    application.include_router(preferences.router)

    @application.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()

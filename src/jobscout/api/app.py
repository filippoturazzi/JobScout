"""ASGI application. Run with ``jobscout serve`` or ``uvicorn jobscout.api.app:app``."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from jobscout import __version__
from jobscout.api.routers import jobs, matches, my_jobs, runs, searches, sources, status
from jobscout.config import get_settings
from jobscout.db import DatabaseNeedsUpgradeError, get_engine, init_db
from jobscout.logs import configure_logging
from jobscout.matching.llm import MissingProviderError
from jobscout.pipeline.conversation import InvalidAnswerError, QuestionsPendingError
from jobscout.pipeline.searches import SearchNotFoundError
from jobscout.pipeline.users import get_or_create_default_user
from jobscout.scheduler import JobScoutScheduler, SearchBusyError

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = get_engine(settings)
    try:
        init_db(engine)
    except DatabaseNeedsUpgradeError as exc:
        log.error("%s", exc)  # the one sentence a user needs, above uvicorn's traceback
        raise
    with Session(engine) as session:
        get_or_create_default_user(session)
    # A fresh scheduler per lifespan, so start() can never run twice on one instance.
    scheduler = JobScoutScheduler(engine, settings)
    application.state.scheduler = scheduler
    try:
        scheduler.start()
        yield
    finally:
        scheduler.shutdown()


def _add_error_handlers(application: FastAPI) -> None:
    def refuse(
        status: int, exc: Exception, code: str | None = None, **extra: object
    ) -> JSONResponse:
        body: dict[str, object] = {"detail": str(exc)}
        if code is not None:
            body["code"] = code
        return JSONResponse(status_code=status, content={**body, **extra})

    @application.exception_handler(MissingProviderError)
    def _no_key(_: Request, exc: Exception) -> JSONResponse:
        return refuse(409, exc, "no_llm_key")

    @application.exception_handler(SearchNotFoundError)
    def _not_found(_: Request, exc: Exception) -> JSONResponse:
        return refuse(404, exc)

    @application.exception_handler(SearchBusyError)
    def _busy(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, SearchBusyError)
        return refuse(409, exc, "search_busy", search_id=exc.search_id)

    @application.exception_handler(QuestionsPendingError)
    def _pending(_: Request, exc: Exception) -> JSONResponse:
        return refuse(409, exc, "questions_pending")

    @application.exception_handler(InvalidAnswerError)
    def _invalid(_: Request, exc: Exception) -> JSONResponse:
        return refuse(422, exc)


def create_app() -> FastAPI:
    # Here, not only in the CLI: every way of serving this app builds it through this function,
    # so every way gets LOG_LEVEL applied and an invalid config stops the process.
    configure_logging()
    application = FastAPI(title="JobScout", version=__version__, lifespan=lifespan)
    application.include_router(jobs.router)
    application.include_router(matches.router)
    application.include_router(my_jobs.router)
    application.include_router(runs.router)
    application.include_router(searches.router)
    application.include_router(sources.router)
    application.include_router(status.router)
    _add_error_handlers(application)

    @application.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    web_dir = Path(str(files("jobscout") / "web"))

    @application.get("/", include_in_schema=False)
    def page() -> FileResponse:
        return FileResponse(
            web_dir / "index.html", media_type="text/html", headers={"Cache-Control": "no-cache"}
        )

    # Mounted last: every API route above keeps its path.
    application.mount("/static", StaticFiles(directory=web_dir), name="static")
    return application


app = create_app()

"""Engine and session helpers. SQLite by default; any SQLAlchemy URL via DATABASE_URL."""

from typing import Any

from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from jobscout import models  # noqa: F401  (registers tables on SQLModel.metadata)
from jobscout.config import Settings, get_settings


def create_engine_from_url(url: str) -> Engine:
    if url.startswith("sqlite"):
        kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            # One shared in-memory database across connections (tests).
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url)


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


_engines: dict[str, Engine] = {}


def get_engine(settings: Settings | None = None) -> Engine:
    """One engine per DATABASE_URL, shared by the CLI, the API lifespan and (stage 3) the
    scheduler."""
    url = (settings or get_settings()).database_url
    if url not in _engines:
        _engines[url] = create_engine_from_url(url)
    return _engines[url]


def reset_engines() -> None:
    """Dispose and forget every cached engine (tests, or after changing settings)."""
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()

"""Engine and session helpers. SQLite by default; any SQLAlchemy URL via DATABASE_URL."""

from functools import lru_cache

from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from jobscout import models  # noqa: F401  (registers tables on SQLModel.metadata)
from jobscout.config import get_settings


def create_engine_from_url(url: str) -> Engine:
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            # One shared in-memory database across connections (tests).
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url)


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


@lru_cache
def get_engine() -> Engine:
    return create_engine_from_url(get_settings().database_url)

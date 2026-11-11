"""Engine and session helpers. SQLite by default; any SQLAlchemy URL via DATABASE_URL."""

import threading
from typing import Any

from sqlalchemy import Engine, inspect
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
    # A database server can restart under a long-running app (Docker updates, OOM); pre-ping
    # swaps a dead pooled connection for a fresh one instead of failing the next query.
    return create_engine(url, pool_pre_ping=True)


class DatabaseNeedsUpgradeError(RuntimeError):
    """The database predates saved searches or run sources; `jobscout upgrade-db` fixes it."""


def needs_searches_conversion(engine: Engine) -> bool:
    """True when `user_preferences` exists without `search_id`, the pre-searches shape."""
    inspector = inspect(engine)
    if not inspector.has_table("user_preferences"):
        return False
    columns = {column["name"] for column in inspector.get_columns("user_preferences")}
    return "search_id" not in columns


def needs_upgrade(engine: Engine) -> bool:
    """True for the pre-searches shape, or when table `run` lacks its `sources` column."""
    if needs_searches_conversion(engine):
        return True
    inspector = inspect(engine)
    if not inspector.has_table("run"):
        return False
    return "sources" not in {column["name"] for column in inspector.get_columns("run")}


def init_db(engine: Engine) -> None:
    # Checked first: create_all would add the new tables beside the old ones, and every
    # query would then fail with a SQL error instead of this sentence.
    if needs_upgrade(engine):
        raise DatabaseNeedsUpgradeError(
            "This database is out of date. Back it up and run `jobscout upgrade-db`."
        )
    SQLModel.metadata.create_all(engine)


_engines: dict[str, Engine] = {}
_engines_lock = threading.Lock()


def get_engine(settings: Settings | None = None) -> Engine:
    """One engine per DATABASE_URL, shared by the CLI, the API lifespan and the scheduler."""
    url = (settings or get_settings()).database_url
    with _engines_lock:
        if url not in _engines:
            _engines[url] = create_engine_from_url(url)
        return _engines[url]


def reset_engines() -> None:
    """Dispose and forget every cached engine (tests, or after changing settings)."""
    with _engines_lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session

from jobscout.db import create_engine_from_url, init_db

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def engine():
    engine = create_engine_from_url("sqlite://")
    init_db(engine)
    return engine


@pytest.fixture
def session(engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _isolate_engines(monkeypatch):
    """Every test starts and ends without cached engines or cached settings.

    The scheduler is disabled by default: otherwise every test that builds the app would
    spawn background threads, and a wake would run the real pipeline on a pool thread.
    """
    from jobscout.config import get_settings
    from jobscout.db import reset_engines

    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    reset_engines()
    get_settings.cache_clear()
    yield
    reset_engines()
    get_settings.cache_clear()

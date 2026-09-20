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

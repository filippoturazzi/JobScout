from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from jobscout.api.app import app
from jobscout.api.deps import get_session


@pytest.fixture
def client(engine) -> Iterator[TestClient]:
    def _override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override
    # No `with` block on purpose: skipping the lifespan keeps the real engine out of tests.
    yield TestClient(app)
    app.dependency_overrides.clear()

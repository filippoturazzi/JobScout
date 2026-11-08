from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from jobscout.api.app import app
from jobscout.api.deps import get_chat_model, get_session
from jobscout.matching.terms import _LLMOutput
from jobscout.models import Run
from tests.matching.fakes import CountingChatModel


@pytest.fixture
def client(engine) -> Iterator[TestClient]:
    def _override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override
    # No `with` block on purpose: skipping the lifespan keeps the real engine out of tests.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def chat(monkeypatch) -> CountingChatModel:
    """A provider key is set and every reading comes from this fake, complete by default."""
    monkeypatch.setenv("LLM_PROVIDER", "google")
    monkeypatch.setenv("GOOGLE_API_KEY", "test")
    model = CountingChatModel(results=[reading()])
    app.dependency_overrides[get_chat_model] = lambda: model
    return model


def reading(**kw) -> _LLMOutput:
    """A reading with no question left to ask, unless `kw` removes something."""
    fields = {
        "terms": ["ai engineer"],
        "seniority": ["junior"],
        "required_skills": ["Python"],
        "stated_work_modes": ["remote"],
        "stated_regions": ["Portugal"],
    }
    return _LLMOutput(**{**fields, **kw})


class FakeScheduler:
    """Stands in for `app.state.scheduler`: opens the run row, runs nothing."""

    def __init__(self, engine) -> None:
        self._engine = engine
        self.running: tuple[int, int] | None = None
        self.started: list[tuple[int, bool]] = []

    def running_search(self) -> tuple[int, int] | None:
        return self.running

    def start_search(self, search_id: int, fetch: bool = True) -> int:
        self.started.append((search_id, fetch))
        with Session(self._engine) as session:
            run = Run(job="search", user_id=1, search_id=search_id)
            session.add(run)
            session.commit()
            assert run.id is not None
            return run.id


@pytest.fixture
def fake_scheduler(engine, monkeypatch) -> FakeScheduler:
    scheduler = FakeScheduler(engine)
    monkeypatch.setattr(app.state, "scheduler", scheduler, raising=False)
    return scheduler

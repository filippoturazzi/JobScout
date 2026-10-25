import threading
import time

import pytest
from sqlmodel import select

from jobscout.api.app import app
from jobscout.config import Settings
from jobscout.models import Run, User
from jobscout.models.base import utcnow
from jobscout.scheduler import JobScoutScheduler


class _Held:
    """Stands in for `search_job`: records the call, then waits until the test releases it."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.started = threading.Event()
        self.calls: list[tuple[int, int]] = []

    def __call__(self, engine, settings, user_id, run_id) -> None:
        self.calls.append((user_id, run_id))
        self.started.set()
        self.release.wait(5)


@pytest.fixture
def held(engine, monkeypatch):
    work = _Held()
    monkeypatch.setattr("jobscout.scheduler.search_job", work)
    # Disabled on purpose: a user's search must run even when the periodic jobs are off.
    scheduler = JobScoutScheduler(engine, Settings(_env_file=None, scheduler_enabled=False))
    scheduler.start()
    monkeypatch.setattr(app.state, "scheduler", scheduler, raising=False)
    work.scheduler = scheduler
    yield work
    work.release.set()
    scheduler.shutdown()


def _user_id(client, session) -> int:
    client.get("/preferences")  # creates the default user
    user = session.exec(select(User)).one()
    assert user.id is not None
    return user.id


def test_post_search_returns_a_run_id_immediately(client, session, held):
    user_id = _user_id(client, session)
    response = client.post("/search")
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert held.started.wait(5), "the search was never scheduled"
    assert held.calls == [(user_id, run_id)]
    run = session.get(Run, run_id)
    assert run is not None
    assert (run.job, run.user_id, run.finished_at) == ("search", user_id, None)


def test_a_second_search_returns_the_run_already_in_flight(client, session, held):
    _user_id(client, session)
    first = client.post("/search").json()["run_id"]
    assert held.started.wait(5)
    second = client.post("/search").json()["run_id"]
    assert second == first
    assert len(held.calls) == 1


def test_a_search_after_the_last_one_finished_starts_a_new_run(client, session, held):
    user_id = _user_id(client, session)
    first = client.post("/search").json()["run_id"]
    assert held.started.wait(5)
    held.release.set()
    deadline = time.monotonic() + 5
    while held.scheduler.search_in_flight(user_id) is not None:
        assert time.monotonic() < deadline, "the finished search was never released"
        time.sleep(0.02)
    second = client.post("/search").json()["run_id"]
    assert second != first


def test_a_user_initiated_search_is_never_skipped_by_the_backoff(client, session, held):
    user_id = _user_id(client, session)
    for _ in range(6):  # a deep failure streak for every job the backoff could read
        session.add(Run(job="search", user_id=user_id, ok=False, finished_at=utcnow()))
        session.add(Run(job="match", ok=False, finished_at=utcnow()))
    session.commit()
    client.post("/search")
    assert held.started.wait(5), "a failure streak must not stop the user's search"


def test_get_search_reports_progress_counters(client, session):
    user_id = _user_id(client, session)
    run = Run(job="search", user_id=user_id, counters={"fetched": 12, "remaining": 30})
    session.add(run)
    session.commit()
    body = client.get(f"/search/{run.id}").json()
    assert body["counters"] == {"fetched": 12, "remaining": 30}
    assert body["finished_at"] is None


def test_get_search_is_404_for_another_job_or_an_unknown_id(client, session):
    _user_id(client, session)
    ingest = Run(job="ingest")
    session.add(ingest)
    session.commit()
    assert client.get(f"/search/{ingest.id}").status_code == 404
    assert client.get("/search/9999").status_code == 404


def test_post_search_without_a_scheduler_is_503(client, session, monkeypatch):
    _user_id(client, session)
    monkeypatch.delattr(app.state, "scheduler", raising=False)
    assert client.post("/search").status_code == 503

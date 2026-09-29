from datetime import timedelta

import pytest
from sqlmodel import Session, select

from jobscout.config import Settings
from jobscout.models import Run
from jobscout.models.base import utcnow
from jobscout.scheduler import finish_run, should_skip_for_backoff, start_run


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_start_run_writes_a_pessimistic_row(session: Session):
    """The row lands before the work does, so a killed process leaves a failure behind."""
    run = start_run(session, _settings(), "ingest")

    stored = session.exec(select(Run)).one()
    assert (stored.id, stored.job, stored.ok, stored.finished_at) == (run.id, "ingest", False, None)


def test_finish_run_records_counters(session: Session):
    run = start_run(session, _settings(), "match")

    finish_run(session, run, ok=True, counters={"evaluated": 4})

    stored = session.exec(select(Run)).one()
    assert (stored.ok, stored.counters, stored.error) == (True, {"evaluated": 4}, None)
    assert stored.finished_at is not None


def test_finish_run_records_the_failure_message(session: Session):
    run = start_run(session, _settings(), "match")

    finish_run(session, run, ok=False, counters={}, error="RuntimeError: 429")

    stored = session.exec(select(Run)).one()
    assert (stored.ok, stored.error) == (False, "RuntimeError: 429")


def test_start_run_prunes_rows_past_the_retention_window(session: Session):
    old = Run(job="ingest", started_at=utcnow() - timedelta(days=40), ok=True)
    recent = Run(job="ingest", started_at=utcnow() - timedelta(days=5), ok=True)
    session.add(old)
    session.add(recent)
    session.commit()

    start_run(session, _settings(run_retention_days=30), "ingest")

    remaining = session.exec(select(Run)).all()
    assert len(remaining) == 2, "the 40-day-old row is gone; the 5-day-old one and the new one stay"


def _record(session: Session, job: str, ok: bool) -> None:
    session.add(Run(job=job, ok=ok, finished_at=utcnow()))
    session.commit()


def test_no_history_never_skips(session: Session):
    assert should_skip_for_backoff(session, _settings(), "match", tick=1) is False


@pytest.mark.parametrize("tick,expected", [(1, True), (2, False), (3, True), (4, False)])
def test_one_failure_halves_the_rate(session: Session, tick: int, expected: bool):
    _record(session, "match", ok=False)

    assert should_skip_for_backoff(session, _settings(), "match", tick=tick) is expected


def test_failures_compound(session: Session):
    """Three consecutive failures means every 8th tick."""
    for _ in range(3):
        _record(session, "match", ok=False)

    assert should_skip_for_backoff(session, _settings(), "match", tick=7) is True
    assert should_skip_for_backoff(session, _settings(), "match", tick=8) is False


def test_a_success_resets_the_count(session: Session):
    for _ in range(3):
        _record(session, "match", ok=False)
    _record(session, "match", ok=True)

    assert should_skip_for_backoff(session, _settings(), "match", tick=1) is False


def test_the_backoff_is_capped(session: Session):
    for _ in range(40):
        _record(session, "match", ok=False)

    settings = _settings(max_backoff_ticks=2)

    assert should_skip_for_backoff(session, settings, "match", tick=4) is False, "2**2, not 2**40"


def test_another_jobs_failures_do_not_slow_this_one(session: Session):
    for _ in range(5):
        _record(session, "ingest", ok=False)

    assert should_skip_for_backoff(session, _settings(), "match", tick=1) is False

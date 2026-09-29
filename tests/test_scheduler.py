from datetime import timedelta

from sqlmodel import Session, select

from jobscout.config import Settings
from jobscout.models import Run
from jobscout.models.base import utcnow
from jobscout.scheduler import finish_run, start_run


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

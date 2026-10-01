from sqlmodel import Session, select

from jobscout.models import RUN_JOBS, Run
from jobscout.models.base import utcnow


def test_run_defaults_to_an_unfinished_failure():
    """A row is written before the work starts, so the default must be the pessimistic one:
    a process killed mid-run leaves a trace that reads as a failure, not a success."""
    run = Run(job="ingest")

    assert run.ok is False
    assert run.finished_at is None
    assert run.counters == {}


def test_run_round_trips_counters(session: Session):
    session.add(Run(job="match", counters={"evaluated": 3, "skipped_low": 7}))
    session.commit()

    stored = session.exec(select(Run)).one()

    assert stored.counters == {"evaluated": 3, "skipped_low": 7}
    assert stored.started_at <= utcnow()


def test_run_jobs_lists_both_scheduled_jobs():
    assert frozenset({"ingest", "match"}) == RUN_JOBS

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


def test_run_jobs_lists_every_job_that_records_a_run():
    assert frozenset({"ingest", "match", "digest", "search"}) == RUN_JOBS


def test_a_run_is_instance_global_unless_a_user_is_named(session: Session):
    """`search` is one user's; ingest, match and digest are the whole instance's."""
    session.add(Run(job="ingest"))
    session.add(Run(job="search", user_id=7))
    session.commit()

    by_job = {run.job: run.user_id for run in session.exec(select(Run)).all()}

    assert by_job == {"ingest": None, "search": 7}

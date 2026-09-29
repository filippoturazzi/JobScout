from datetime import timedelta

import pytest
from sqlmodel import Session, col, select

from jobscout.config import Settings
from jobscout.models import Job, Run
from jobscout.models.base import utcnow
from jobscout.scheduler import (
    finish_run,
    ingest_job,
    match_job,
    should_skip_for_backoff,
    start_run,
)


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


def test_ordering_by_time_not_insertion_order(session: Session):
    """Ordering must use started_at time, not insertion order (id).

    Insert a newer success first, then an older failure, to verify that the
    backoff walk sees the newer success and resets the count.
    """
    now = utcnow()
    older_time = now - timedelta(hours=2)
    newer_time = now - timedelta(hours=1)

    # Insert the newer success FIRST
    session.add(Run(job="match", ok=True, started_at=newer_time, finished_at=newer_time))
    session.commit()

    # Then insert the older failure
    session.add(Run(job="match", ok=False, started_at=older_time, finished_at=older_time))
    session.commit()

    # The function should see the newer success first (by time), not the older failure (by id)
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


def _add_stale_job(session: Session, source: str, external_id: str, days_ago: int) -> Job:
    seen = utcnow() - timedelta(days=days_ago)
    job = Job(
        source=source,
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        remote=True,
        url=f"https://x/{external_id}",
        description="Python LLM work.",
        content_hash=f"h-{external_id}",
        first_seen_at=seen,
        last_seen_at=seen,
        is_active=True,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_ingest_job_records_counters_and_deactivates(session: Session, monkeypatch):
    """A source that answered expires its own stale jobs; a source that errored keeps its own."""
    import jobscout.scheduler as scheduler_module
    from jobscout.pipeline.ingest import IngestResult

    engine = session.get_bind()
    stale_ok = _add_stale_job(session, "arbeitnow", "gone", days_ago=30)
    stale_broken = _add_stale_job(session, "remotive", "kept", days_ago=30)

    def _fake_ingest(_session, _settings, sources=None):
        return [
            IngestResult(source="arbeitnow", fetched=5, created=2, updated=3),
            IngestResult(source="remotive", error="HTTPStatusError: 503"),
        ]

    monkeypatch.setattr(scheduler_module, "run_ingest", _fake_ingest)

    ingest_job(engine, _settings(inactive_after_days=14))

    stored = session.exec(select(Run).where(col(Run.job) == "ingest")).one()
    assert stored.ok is False
    assert stored.error == "remotive: HTTPStatusError: 503"
    assert stored.counters["created"] == 2
    assert stored.counters["deactivated"] == 1
    session.expire_all()
    assert session.get(Job, stale_ok.id).is_active is False
    assert session.get(Job, stale_broken.id).is_active is True


def test_ingest_job_records_a_crash_instead_of_raising(session: Session, monkeypatch):
    """A raising job must leave its Run row behind with the message, not roll it away."""
    import jobscout.scheduler as scheduler_module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(scheduler_module, "run_ingest", _boom)

    ingest_job(session.get_bind(), _settings())

    stored = session.exec(select(Run)).one()
    assert (stored.ok, stored.error) == (False, "RuntimeError: connection reset")
    assert stored.finished_at is not None


def test_match_job_skipped_by_backoff_writes_no_row(session: Session):
    """Skipping must not itself count as a failure, or the backoff would stall forever."""
    _record(session, "match", ok=False)

    match_job(session.get_bind(), _settings(), tick=1)

    rows = session.exec(select(Run).where(col(Run.job) == "match")).all()
    assert len(rows) == 1, "only the seeded failure; the skipped tick added nothing"


def test_match_job_records_a_crash_instead_of_raising(session: Session, monkeypatch):
    import jobscout.scheduler as scheduler_module
    from jobscout.pipeline.users import get_or_create_default_user

    get_or_create_default_user(session)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("429")

    monkeypatch.setattr(scheduler_module, "run_match", _boom)

    match_job(session.get_bind(), _settings())

    stored = session.exec(select(Run).where(col(Run.job) == "match")).one()
    assert (stored.ok, stored.error) == (False, "RuntimeError: 429")

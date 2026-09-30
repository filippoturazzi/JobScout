from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, col, select

from jobscout.config import Settings
from jobscout.models import Job, Match, Run, User
from jobscout.models.base import utcnow
from jobscout.pipeline.matching import MatchRun
from jobscout.pipeline.run import save_preferences
from jobscout.pipeline.users import get_or_create_default_user
from jobscout.scheduler import (
    JobScoutScheduler,
    finish_run,
    ingest_job,
    match_job,
    should_skip_for_backoff,
    start_run,
    wake_matching,
)
from tests.matching.fakes import CountingChatModel, DeterministicFakeEmbedding


def _settings(**kw) -> Settings:
    kw.setdefault("scheduler_enabled", True)  # the suite-wide env default is off
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
    assert stored.ok is True, "partial failure is not run failure"
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


def test_ingest_job_total_failure_is_a_failed_run(session: Session, monkeypatch):
    """When every source errors the run fails, which is what keeps the backoff working."""
    import jobscout.scheduler as scheduler_module
    from jobscout.pipeline.ingest import IngestResult

    monkeypatch.setattr(
        scheduler_module,
        "run_ingest",
        lambda *_a, **_k: [
            IngestResult(source="arbeitnow", error="timeout"),
            IngestResult(source="remotive", error="503"),
        ],
    )

    ingest_job(session.get_bind(), _settings())

    stored = session.exec(select(Run)).one()
    assert stored.ok is False
    assert stored.error == "arbeitnow: timeout; remotive: 503"


def test_ingest_job_with_no_results_is_a_failed_run(session: Session, monkeypatch):
    import jobscout.scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module, "run_ingest", lambda *_a, **_k: [])

    ingest_job(session.get_bind(), _settings())

    stored = session.exec(select(Run)).one()
    assert stored.ok is False


def test_ingest_job_does_not_report_rolled_back_deactivations(session: Session, monkeypatch):
    """`deactivated` lives in the job's transaction: a rollback must not leave it claimed."""
    import jobscout.scheduler as scheduler_module
    from jobscout.pipeline.ingest import IngestResult

    jobs = [
        _add_stale_job(session, "arbeitnow", "a", days_ago=30),
        _add_stale_job(session, "arbeitnow", "b", days_ago=30),
        _add_stale_job(session, "remotive", "c", days_ago=30),
    ]
    monkeypatch.setattr(
        scheduler_module,
        "run_ingest",
        lambda *_a, **_k: [
            IngestResult(source="arbeitnow", created=1),
            IngestResult(source="remotive", created=1),
        ],
    )
    real = scheduler_module.deactivate_stale_jobs

    def _second_raises(sess, settings, source):
        if source == "remotive":
            raise RuntimeError("disk full")
        return real(sess, settings, source)

    monkeypatch.setattr(scheduler_module, "deactivate_stale_jobs", _second_raises)

    ingest_job(session.get_bind(), _settings(inactive_after_days=14))

    stored = session.exec(select(Run).where(col(Run.job) == "ingest")).one()
    assert (stored.ok, stored.error) == (False, "RuntimeError: disk full")
    assert stored.counters["deactivated"] == 0
    session.expire_all()
    assert all(session.get(Job, j.id).is_active for j in jobs)


def test_jobs_never_raise_even_when_the_run_row_cannot_be_written(
    session: Session, monkeypatch, caplog
):
    import jobscout.scheduler as scheduler_module

    def _boom(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(scheduler_module, "start_run", _boom)

    ingest_job(session.get_bind(), _settings())
    match_job(session.get_bind(), _settings())

    assert "ingest job crashed" in caplog.text
    assert "match job crashed" in caplog.text


def _fake_match(results: dict[int, MatchRun]):
    def _run(_session, _settings, user_id, **_kw):
        return results[user_id]

    return _run


def _two_users(session: Session) -> tuple[int, int]:
    first = get_or_create_default_user(session)
    second = User(email="second@example.com")
    session.add(second)
    session.commit()
    session.refresh(second)
    assert first.id is not None and second.id is not None
    return first.id, second.id


def test_match_job_aggregates_counters_across_users(session: Session, monkeypatch):
    import jobscout.scheduler as scheduler_module

    a, b = _two_users(session)
    monkeypatch.setattr(
        scheduler_module,
        "run_match",
        _fake_match(
            {
                a: MatchRun(
                    candidates=5, evaluated=3, skipped_low=2, embedded=4, embeddings_pending=1
                ),
                b: MatchRun(candidates=2, evaluated=1, skipped_low=1, embedded=2, errors=["x"]),
            }
        ),
    )

    match_job(session.get_bind(), _settings())

    stored = session.exec(select(Run).where(col(Run.job) == "match")).one()
    assert stored.ok is True
    assert stored.error is None
    assert stored.counters == {
        "candidates": 7,
        "evaluated": 4,
        "skipped_low": 3,
        "embedded": 6,
        "embeddings_pending": 1,
        "errors": 1,
    }


def test_match_job_where_every_evaluation_failed_is_a_failed_run(session: Session, monkeypatch):
    """Otherwise a rate-limited provider never triggers the backoff."""
    import jobscout.scheduler as scheduler_module

    a = get_or_create_default_user(session).id
    assert a is not None
    monkeypatch.setattr(
        scheduler_module,
        "run_match",
        _fake_match({a: MatchRun(candidates=3, errors=["RuntimeError: 429"] * 3)}),
    )

    match_job(session.get_bind(), _settings())

    stored = session.exec(select(Run).where(col(Run.job) == "match")).one()
    assert stored.ok is False
    assert stored.error is not None and "RuntimeError: 429" in stored.error


def test_match_job_that_only_skipped_low_similarity_is_a_success(session: Session, monkeypatch):
    import jobscout.scheduler as scheduler_module

    a = get_or_create_default_user(session).id
    assert a is not None
    monkeypatch.setattr(
        scheduler_module,
        "run_match",
        _fake_match({a: MatchRun(candidates=4, skipped_low=4)}),
    )

    match_job(session.get_bind(), _settings())

    assert session.exec(select(Run).where(col(Run.job) == "match")).one().ok is True


def test_start_registers_both_jobs_at_the_configured_intervals(session: Session):
    scheduler = JobScoutScheduler(
        session.get_bind(),
        _settings(
            ingest_interval_minutes=42, match_interval_minutes=7, scheduler_jitter_seconds=13
        ),
    )
    scheduler.start()
    try:
        by_id = {job.id: job for job in scheduler.get_jobs()}

        assert set(by_id) == {"ingest", "match"}
        for job in by_id.values():
            assert job.max_instances == 1
            assert job.coalesce is True
            assert job.trigger.jitter == 13
        assert by_id["ingest"].trigger.interval.total_seconds() == 42 * 60
        assert by_id["match"].trigger.interval.total_seconds() == 7 * 60
    finally:
        scheduler.shutdown()


def test_disabled_scheduler_registers_nothing(session: Session):
    """Otherwise every test that builds the app would start threads."""
    scheduler = JobScoutScheduler(session.get_bind(), _settings(scheduler_enabled=False))
    scheduler.start()
    try:
        assert scheduler.get_jobs() == []
    finally:
        scheduler.shutdown()


def test_wake_adds_one_immediate_run_and_repeats_collapse(session: Session, monkeypatch):
    # Stubbed: the woken run fires within milliseconds and must not touch the real pipeline.
    monkeypatch.setattr("jobscout.scheduler.match_job", lambda engine, settings, tick=0: None)
    scheduler = JobScoutScheduler(session.get_bind(), _settings())
    scheduler.start()
    try:
        scheduler.wake_matching()
        scheduler.wake_matching()

        wakes = [job for job in scheduler.get_jobs() if job.id == "match-wake"]
        assert len(wakes) == 1, "a second save must replace the pending run, not queue another"
    finally:
        scheduler.shutdown()


def test_wake_is_scheduled_for_now_not_shifted_by_the_utc_offset(session: Session, monkeypatch):
    """A naive UTC run_date is read as local time by APScheduler, delaying the wake by hours
    on UTC-negative machines. The scheduler zone is pinned to a non-UTC one so this fails on a
    UTC host (CI) too. Pause the scheduler so nothing fires, then check the time."""
    monkeypatch.setattr(
        "jobscout.scheduler.BackgroundScheduler",
        lambda: BackgroundScheduler(timezone=ZoneInfo("America/New_York")),
    )
    scheduler = JobScoutScheduler(session.get_bind(), _settings())
    scheduler.start()
    try:
        scheduler._scheduler.pause()
        scheduler.wake_matching()

        wake = next(job for job in scheduler.get_jobs() if job.id == "match-wake")
        drift = abs((wake.trigger.run_date - datetime.now(UTC)).total_seconds())
        assert drift < 5
    finally:
        scheduler.shutdown()


def test_wake_without_a_scheduler_is_a_no_op():
    """The CLI and a scheduler-less API both call this; it must never raise."""
    wake_matching(None)


def test_shutdown_is_safe_before_start(session: Session):
    JobScoutScheduler(session.get_bind(), _settings()).shutdown()


def test_each_match_firing_gets_the_next_tick(session: Session, monkeypatch):
    """A skipped firing must still advance the counter, or a backed-off job never runs again."""
    seen: list[int] = []
    monkeypatch.setattr(
        "jobscout.scheduler.match_job", lambda engine, settings, tick=0: seen.append(tick)
    )
    scheduler = JobScoutScheduler(session.get_bind(), _settings())

    scheduler._run_match_tick()
    scheduler._run_match_tick()

    assert seen == [1, 2]


def test_an_overlapping_match_firing_is_dropped_but_still_counted(session: Session, monkeypatch):
    """A wake must not run beside a scheduled match: the in-flight run's ok=False row would
    read as a failure and deepen the backoff against itself."""
    seen: list[int] = []
    scheduler = JobScoutScheduler(session.get_bind(), _settings())

    def in_flight(engine, settings, tick=0):
        seen.append(tick)
        scheduler._run_match_tick()  # a wake arriving while this run is executing

    monkeypatch.setattr("jobscout.scheduler.match_job", in_flight)

    scheduler._run_match_tick()

    assert seen == [1], "the nested firing must not reach match_job"
    assert scheduler._match_tick == 2
    scheduler._run_match_tick()
    assert seen == [1, 3], "the guard must be released after the run"


def test_a_preference_save_leads_to_scored_matches(session: Session, monkeypatch):
    """The stage's headline: save preferences -> stale -> re-score, through the real path.

    A match scored under the old preferences exists. save_preferences must stale it and call
    the `on_changed` hook (here a recorder; the real wake_matching and the scheduler wiring
    are covered by other tests). match_job then re-scores the row and records a Run, with
    fake models standing in only for the provider.
    """
    import jobscout.pipeline.matching as matching_module

    monkeypatch.setattr(matching_module, "chat_model", lambda _s: CountingChatModel())
    monkeypatch.setattr(matching_module, "embeddings", lambda _s: DeterministicFakeEmbedding(8))
    settings = _settings(embedding_dim=8, similarity_threshold=-1.0, scheduler_enabled=False)
    engine = session.get_bind()
    user = get_or_create_default_user(session)
    job = _add_stale_job(session, "arbeitnow", "live", days_ago=0)
    assert job.id is not None and user.id is not None
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.5, score=10, status="new"))
    session.commit()

    woken: list[bool] = []
    save_preferences(
        session,
        settings,
        user.id,
        {"profile_summary": "Python LLM engineer."},
        on_changed=lambda: woken.append(True),
    )
    assert woken == [True], "the save asks for a run"

    match_job(engine, settings, tick=1)

    session.expire_all()
    stored = session.exec(select(Match)).one()
    assert stored.score == 75, "re-scored by the fake model, not the old score of 10"
    assert stored.status != "stale", "the save staled the row and the run cleared it"
    run = session.exec(select(Run).where(col(Run.job) == "match")).one()
    assert (run.ok, run.counters["evaluated"]) == (True, 1)

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import Session, col, select

from jobscout.config import Settings
from jobscout.models import Job, Match, Run, User, UserPreferences
from jobscout.models.base import utcnow
from jobscout.pipeline.matching import MatchRun
from jobscout.pipeline.run import save_preferences
from jobscout.pipeline.users import get_or_create_default_user
from jobscout.scheduler import (
    JobScoutScheduler,
    digest_job,
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
    """Assert WHICH rows survive: an inverted predicate also leaves two rows behind."""
    now = utcnow()
    days = 30
    ages = {
        "old": timedelta(days=40),
        "just_past": timedelta(days=days, seconds=5),
        "recent": timedelta(days=5),
    }
    for label, age in ages.items():
        session.add(Run(job=label, started_at=now - age, ok=True))
    session.commit()

    new_run = start_run(session, _settings(run_retention_days=days), "ingest")

    survivors = {run.job for run in session.exec(select(Run)).all()}
    assert survivors == {"recent", "ingest"}, "expired rows go, recent ones and the new one stay"
    assert new_run.id is not None


def test_a_row_exactly_at_the_retention_limit_is_kept(session: Session, monkeypatch):
    """The predicate is a strict `<`: at exactly RUN_RETENTION_DAYS old, the row stays."""
    import jobscout.scheduler as scheduler_module

    frozen = utcnow()
    monkeypatch.setattr(scheduler_module, "utcnow", lambda: frozen)
    session.add(Run(job="boundary", started_at=frozen - timedelta(days=30), ok=True))
    session.add(Run(job="past", started_at=frozen - timedelta(days=30, microseconds=1), ok=True))
    session.commit()

    start_run(session, _settings(run_retention_days=30), "ingest")

    survivors = {run.job for run in session.exec(select(Run)).all()}
    assert "boundary" in survivors
    assert "past" not in survivors


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


def _record_aged(session: Session, job: str, ok: bool, age: timedelta) -> None:
    """A finished run that started (and ended) `age` ago."""
    when = utcnow() - age
    session.add(Run(job=job, ok=ok, started_at=when, finished_at=when))
    session.commit()


def test_failures_older_than_the_window_do_not_back_off(session: Session):
    """The digest writes no row when nothing qualifies, so a stale streak would otherwise
    stay the newest evidence until the retention prune drops it 30 days later."""
    for _ in range(6):
        _record_aged(session, "digest", ok=False, age=timedelta(hours=48))

    assert should_skip_for_backoff(session, _settings(), "digest", tick=1) is False
    assert should_skip_for_backoff(session, _settings(), "digest", tick=63) is False


def test_only_failures_inside_the_window_count(session: Session):
    """Three old failures plus one recent one must back off like one failure (every 2nd
    tick), not like four (every 16th)."""
    for _ in range(3):
        _record_aged(session, "digest", ok=False, age=timedelta(hours=48))
    _record(session, "digest", ok=False)

    assert should_skip_for_backoff(session, _settings(), "digest", tick=1) is True
    assert should_skip_for_backoff(session, _settings(), "digest", tick=2) is False


def test_a_failure_just_inside_the_window_still_backs_off(session: Session):
    """The boundary belongs to the window: 23 hours old is still evidence about now."""
    _record_aged(session, "match", ok=False, age=timedelta(hours=23))

    assert should_skip_for_backoff(session, _settings(), "match", tick=1) is True


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


def test_start_registers_every_job_at_the_configured_intervals(session: Session):
    scheduler = JobScoutScheduler(
        session.get_bind(),
        _settings(
            ingest_interval_minutes=42,
            match_interval_minutes=7,
            digest_interval_minutes=29,
            scheduler_jitter_seconds=13,
        ),
    )
    scheduler.start()
    try:
        by_id = {job.id: job for job in scheduler.get_jobs()}

        assert set(by_id) == {"ingest", "match", "digest"}
        for job in by_id.values():
            assert job.max_instances == 1
            assert job.coalesce is True
            assert job.trigger.jitter == 13
        assert by_id["ingest"].trigger.interval.total_seconds() == 42 * 60
        assert by_id["match"].trigger.interval.total_seconds() == 7 * 60
        assert by_id["digest"].trigger.interval.total_seconds() == 29 * 60
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
        "jobscout.scheduler.match_job",
        lambda engine, settings, tick=None, force=False: seen.append(tick),
    )
    scheduler = JobScoutScheduler(session.get_bind(), _settings())

    scheduler._run_match_tick()
    scheduler._run_match_tick()

    assert seen == [1, 2]


def test_each_digest_firing_gets_the_next_tick(session: Session, monkeypatch):
    """Every firing is counted, so a backed-off digest still reaches its next due tick."""
    seen: list[int | None] = []
    monkeypatch.setattr(
        "jobscout.scheduler.digest_job",
        lambda engine, settings, tick=None: seen.append(tick),
    )
    scheduler = JobScoutScheduler(session.get_bind(), _settings())

    scheduler._run_digest_tick()
    scheduler._run_digest_tick()

    assert seen == [1, 2]


def test_an_overlapping_match_firing_is_dropped_but_still_counted(session: Session, monkeypatch):
    """A wake must not run beside a scheduled match: the in-flight run's ok=False row would
    read as a failure and deepen the backoff against itself."""
    seen: list[int] = []
    scheduler = JobScoutScheduler(session.get_bind(), _settings())

    def in_flight(engine, settings, tick=None, force=False):
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


# --- C1: the wake must not be swallowed by the backoff on a fresh install ---


def test_a_fresh_install_does_not_accumulate_failed_match_runs(session: Session):
    """No profile means nothing was attempted, and nothing attempted is not everything failed."""
    get_or_create_default_user(session)
    engine = session.get_bind()

    for tick in range(1, 9):
        match_job(engine, _settings(), tick=tick)

    rows = session.exec(select(Run).where(col(Run.job) == "match")).all()
    assert len(rows) == 8, "no failure streak, so the backoff never skipped a tick"
    assert all(row.ok for row in rows)
    assert all(row.error is not None and "No profile summary" in row.error for row in rows)


def test_a_run_with_no_users_is_ok_and_says_why(session: Session):
    match_job(session.get_bind(), _settings(), tick=1)

    stored = session.exec(select(Run).where(col(Run.job) == "match")).one()
    assert stored.ok is True
    assert stored.error is not None and "no users" in stored.error.lower()


def test_a_forced_match_runs_even_when_deep_in_backoff(session: Session, monkeypatch):
    import jobscout.scheduler as scheduler_module

    a = get_or_create_default_user(session).id
    assert a is not None
    for _ in range(5):
        _record(session, "match", ok=False)
    monkeypatch.setattr(
        scheduler_module, "run_match", _fake_match({a: MatchRun(candidates=1, evaluated=1)})
    )
    engine = session.get_bind()

    match_job(engine, _settings(), tick=1)
    assert len(session.exec(select(Run).where(col(Run.job) == "match")).all()) == 5, "backed off"

    match_job(engine, _settings(), tick=1, force=True)

    session.expire_all()
    rows = session.exec(select(Run).where(col(Run.job) == "match")).all()
    assert len(rows) == 6, "the forced run bypassed the backoff"


def test_the_wake_job_forces_and_the_interval_job_does_not(session: Session, monkeypatch):
    seen: list[bool] = []
    monkeypatch.setattr(
        "jobscout.scheduler.match_job",
        lambda engine, settings, tick=None, force=False: seen.append(force),
    )
    scheduler = JobScoutScheduler(session.get_bind(), _settings())

    scheduler._run_match_tick()
    scheduler._run_match_tick(force=True)

    assert seen == [False, True]


def test_wake_registers_a_forced_run(session: Session):
    scheduler = JobScoutScheduler(session.get_bind(), _settings())
    scheduler.start()
    try:
        scheduler.wake_matching()
        wake = next(job for job in scheduler.get_jobs() if job.id == "match-wake")
        assert wake.kwargs == {"force": True}
    finally:
        scheduler.shutdown()


def test_a_genuine_all_errors_run_still_fails_and_still_backs_off(session: Session, monkeypatch):
    import jobscout.scheduler as scheduler_module

    a = get_or_create_default_user(session).id
    assert a is not None
    monkeypatch.setattr(
        scheduler_module,
        "run_match",
        _fake_match({a: MatchRun(candidates=3, errors=["RuntimeError: 429"] * 3)}),
    )
    engine = session.get_bind()

    match_job(engine, _settings(), tick=1)
    match_job(engine, _settings(), tick=1)  # odd tick after one failure: skipped

    rows = session.exec(select(Run).where(col(Run.job) == "match")).all()
    assert [row.ok for row in rows] == [False], "failed once, then the backoff skipped tick 1"


# --- m4 / m7 ---


def test_match_job_without_a_tick_is_never_silently_backed_off_or_skipped(session: Session):
    """tick=None means "no tick known", which must not read as tick 0 (0 % n == 0 for all n)."""
    _record(session, "match", ok=False)
    get_or_create_default_user(session)

    match_job(session.get_bind(), _settings())

    session.expire_all()
    assert len(session.exec(select(Run).where(col(Run.job) == "match")).all()) == 2


def test_an_unfinished_run_does_not_count_toward_the_backoff(session: Session):
    """A run killed mid-flight leaves ok=False, finished_at=NULL; it is not a provider failure."""
    for _ in range(6):
        session.add(Run(job="match", ok=False, finished_at=None))
    session.commit()

    assert should_skip_for_backoff(session, _settings(), "match", tick=1) is False


PINNED_HOUR = 15


@pytest.fixture
def clock(monkeypatch):
    """Pin the digest's notion of "now" to 15:00 local on a fixed date.

    Both clocks the digest reads are pinned to the same instant: `datetime.now()` in the
    scheduler (the send window and the day comparison) and `utcnow()` in `pipeline.digest`
    (the `notified_at` stamp). The "sent today" guard therefore compares real values, just
    ones that cannot straddle midnight whenever the suite happens to run.
    """
    import jobscout.pipeline.digest as digest_module
    import jobscout.scheduler as scheduler_module

    pinned = datetime(2026, 6, 15, PINNED_HOUR, 0).astimezone()

    class _PinnedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return pinned if tz is None else pinned.astimezone(tz)

    monkeypatch.setattr(scheduler_module, "datetime", _PinnedDatetime)
    monkeypatch.setattr(
        digest_module, "utcnow", lambda: pinned.astimezone(UTC).replace(tzinfo=None)
    )
    return pinned


class _RecordingNotifier:
    """Project-owned double. Records sends; optionally fails like a dead SMTP server."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[tuple[str, str]] = []

    def send(self, subject: str, body: str) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append((subject, body))


def _digest_settings(**kw) -> Settings:
    """Settings for a digest test: SMTP is configured, so `digest_job` gets past its
    "can this instance send at all" guard. The notifier itself is still faked — these
    values are never dialled."""
    kw.setdefault("smtp_host", "smtp.test")
    kw.setdefault("smtp_from", "bot@test")
    return _settings(**kw)


def _add_match(session, user_id: int, external_id: str, score: int = 80) -> Match:
    job = Job(
        source="t",
        external_id=external_id,
        title=f"Job {external_id}",
        company="Acme",
        remote=True,
        url=f"https://x/{external_id}",
        description="d",
        content_hash=f"h-{external_id}",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    match = Match(job_id=job.id, user_id=user_id, similarity=0.9, score=score)
    session.add(match)
    session.commit()
    session.refresh(match)
    return match


def _digest_fixture(session, score: int = 80):
    """A user who wants mail and one match worth announcing."""
    from jobscout.pipeline.users import update_preferences

    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"notify_email": "me@example.com"})
    _add_match(session, user.id, "a", score)
    return user


def _second_user(session, address: str | None = "b@example.com") -> User:
    """A second user with one match waiting, and (optionally) an address."""
    from jobscout.pipeline.users import update_preferences

    user = User(email="second@example.com")
    session.add(user)
    session.commit()
    session.refresh(user)
    session.add(UserPreferences(user_id=user.id))
    session.commit()
    if address:
        update_preferences(session, user.id, {"notify_email": address})
    _add_match(session, user.id, "b")
    return user


class _PerRecipient:
    """`build_notifier` double: one recording notifier per address, some of them dead."""

    def __init__(self, dead: frozenset[str] = frozenset()) -> None:
        self.dead = dead
        self.by_address: dict[str, _RecordingNotifier] = {}

    def __call__(self, _settings, recipient):
        error = RuntimeError(f"{recipient} refused") if recipient in self.dead else None
        return self.by_address.setdefault(recipient, _RecordingNotifier(error=error))


def test_digest_job_sends_and_marks_notified(session, monkeypatch, clock):
    import jobscout.scheduler as scheduler_module

    _digest_fixture(session)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)

    digest_job(session.get_bind(), _digest_settings(digest_hour=0), tick=1)

    assert len(notifier.sent) == 1
    session.expire_all()
    assert session.exec(select(Match)).one().notified_at is not None
    run = session.exec(select(Run).where(col(Run.job) == "digest")).one()
    assert (run.ok, run.counters["sent"]) == (True, 1)


def test_digest_job_sends_once_a_day(session, monkeypatch, clock):
    import jobscout.scheduler as scheduler_module

    _digest_fixture(session)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)
    settings = _digest_settings(digest_hour=0)

    digest_job(session.get_bind(), settings, tick=1)

    # A fresh unannounced match arrives after the send. Without it the second firing would
    # find nothing to send and the test would pass even with no once-a-day guard at all:
    # only `already_sent_today` stands between this match and a second e-mail.
    user = session.exec(select(User)).one()
    _add_match(session, user.id, "b", score=90)

    digest_job(session.get_bind(), settings, tick=2)

    assert len(notifier.sent) == 1, "a second firing the same day must not send again"


def test_a_failed_send_marks_nothing_and_retries_next_firing(session, monkeypatch, clock):
    """The matches must survive a dead SMTP server; losing them silently is the worst case."""
    import jobscout.scheduler as scheduler_module

    _digest_fixture(session)
    failing = _RecordingNotifier(error=RuntimeError("smtp down"))
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: failing)
    settings = _digest_settings(digest_hour=0)

    digest_job(session.get_bind(), settings, tick=1)

    session.expire_all()
    assert session.exec(select(Match)).one().notified_at is None
    run = session.exec(select(Run).where(col(Run.job) == "digest")).one()
    assert run.ok is False and "smtp down" in (run.error or "")

    working = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: working)
    digest_job(session.get_bind(), settings, tick=2)

    assert len(working.sent) == 1
    session.expire_all()
    assert session.exec(select(Match)).one().notified_at is not None


def test_digest_job_is_a_no_op_before_the_send_hour(session, monkeypatch, clock):
    import jobscout.scheduler as scheduler_module

    _digest_fixture(session)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)

    # The pinned clock reads 15:00, so a 16:00 send hour has not arrived yet.
    digest_job(session.get_bind(), _digest_settings(digest_hour=PINNED_HOUR + 1), tick=1)

    assert notifier.sent == []
    assert session.exec(select(Run).where(col(Run.job) == "digest")).all() == []


def test_digest_job_writes_no_run_row_when_there_is_nothing_to_send(session, monkeypatch, clock):
    import jobscout.scheduler as scheduler_module
    from jobscout.pipeline.users import update_preferences

    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"notify_email": "me@example.com"})
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: _RecordingNotifier())

    digest_job(session.get_bind(), _digest_settings(digest_hour=0), tick=1)

    assert session.exec(select(Run).where(col(Run.job) == "digest")).all() == []


def test_digest_job_skips_a_user_without_an_address(session, monkeypatch, clock):
    """The user has a qualifying match, so the address guard is the only thing that can
    suppress the send."""
    import jobscout.scheduler as scheduler_module

    user = get_or_create_default_user(session)
    _add_match(session, user.id, "a")
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)

    digest_job(session.get_bind(), _digest_settings(digest_hour=0), tick=1)

    assert notifier.sent == []
    assert session.exec(select(Run).where(col(Run.job) == "digest")).all() == []
    session.expire_all()
    assert session.exec(select(Match)).one().notified_at is None


def _digest_run(session) -> Run:
    session.expire_all()
    return session.exec(select(Run).where(col(Run.job) == "digest")).one()


def test_one_dead_address_does_not_fail_the_run_or_starve_the_others(session, monkeypatch, clock):
    import jobscout.scheduler as scheduler_module

    first = _digest_fixture(session)
    second = _second_user(session)
    router = _PerRecipient(dead=frozenset({"me@example.com"}))
    monkeypatch.setattr(scheduler_module, "build_notifier", router)

    digest_job(session.get_bind(), _digest_settings(digest_hour=0), tick=1)

    assert router.by_address["me@example.com"].sent == []
    assert len(router.by_address["b@example.com"].sent) == 1
    session.expire_all()
    notified = {m.user_id: m.notified_at for m in session.exec(select(Match)).all()}
    assert notified[first.id] is None and notified[second.id] is not None
    run = _digest_run(session)
    assert run.ok is True, "one served user makes the run ok, or one typo starves everyone"
    assert "me@example.com refused" in (run.error or "")
    assert run.counters["users"] == 1


def test_a_run_where_every_user_failed_is_a_failed_run(session, monkeypatch, clock):
    """The other end: without it the digest backoff could never engage."""
    import jobscout.scheduler as scheduler_module

    _digest_fixture(session)
    _second_user(session)
    router = _PerRecipient(dead=frozenset({"me@example.com", "b@example.com"}))
    monkeypatch.setattr(scheduler_module, "build_notifier", router)

    digest_job(session.get_bind(), _digest_settings(digest_hour=0), tick=1)

    run = _digest_run(session)
    assert run.ok is False
    assert run.counters["users"] == 0
    assert should_skip_for_backoff(session, _digest_settings(), "digest", tick=1) is True


def test_digest_run_reports_how_many_rows_the_cap_held_back(session, monkeypatch, clock):
    import jobscout.scheduler as scheduler_module
    from jobscout.pipeline.digest import DIGEST_CAP

    user = _digest_fixture(session)
    for i in range(DIGEST_CAP + 1):  # one already exists: 22 qualify, 20 fit
        _add_match(session, user.id, f"extra{i}")
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)

    digest_job(session.get_bind(), _digest_settings(digest_hour=0), tick=1)

    counters = _digest_run(session).counters
    assert (counters["sent"], counters["held_back"]) == (DIGEST_CAP, 2)


def test_digest_job_without_a_tick_is_never_silently_backed_off(session, monkeypatch, clock):
    """tick=None means "no tick known"; it must not read as tick 0 (0 % n == 0 for all n)."""
    import jobscout.scheduler as scheduler_module

    _digest_fixture(session)
    _record(session, "digest", ok=False)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)

    digest_job(session.get_bind(), _digest_settings(digest_hour=0))

    assert len(notifier.sent) == 1


def test_digest_job_is_a_no_op_without_smtp(session, clock):
    """No SMTP configured is a normal state, not an error — and writes no Run row.

    Deliberately does NOT monkeypatch `build_notifier`: the guard under test reads the
    settings directly, so faking the factory would make this test pass without ever
    exercising it.
    """
    _digest_fixture(session)

    digest_job(session.get_bind(), _settings(digest_hour=0, smtp_host=None), tick=1)

    session.expire_all()
    assert session.exec(select(Match)).one().notified_at is None
    assert session.exec(select(Run).where(col(Run.job) == "digest")).all() == []


def test_a_scored_match_reaches_a_digest_and_is_never_sent_twice(session, monkeypatch, clock):
    """Stage 4's headline: score -> digest -> marked -> never again.

    Drives the real `digest_job`, with a double standing in only for SMTP.
    """
    import jobscout.scheduler as scheduler_module

    _digest_fixture(session, score=88)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)
    settings = _digest_settings(digest_hour=0)

    digest_job(session.get_bind(), settings, tick=1)

    subject, body = notifier.sent[0]
    assert subject == "JobScout: 1 new match"
    assert "[88] Job a — Acme" in body

    # A later day must not re-announce it, even though staling would reset `status`.
    session.expire_all()
    match = session.exec(select(Match)).one()
    match.status = "stale"
    match.notified_at = utcnow() - timedelta(days=2)
    session.add(match)
    session.commit()

    digest_job(session.get_bind(), settings, tick=2)

    assert len(notifier.sent) == 1, "notified_at, not status, decides"


def test_a_crash_after_a_successful_send_finishes_the_run_and_says_the_mail_went_out(
    session, monkeypatch, clock
):
    """The send cannot be un-sent. A crash in the marking must still finish the Run row,
    and /runs must distinguish "nobody got mail" from "they got mail and may get it again".
    """
    import jobscout.scheduler as scheduler_module

    _digest_fixture(session)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)

    def _boom(*_a, **_kw):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(scheduler_module, "mark_notified", _boom)

    digest_job(session.get_bind(), _digest_settings(digest_hour=0), tick=1)

    assert len(notifier.sent) == 1, "the mail really did go out"
    run = _digest_run(session)
    assert run.ok is False
    assert run.finished_at is not None, "a finished row, not one that reads as a killed process"
    assert "database is locked" in (run.error or "")
    assert "SENT BUT NOT MARKED" in (run.error or "")
    assert "me@example.com" in (run.error or "")
    assert session.exec(select(Match)).one().notified_at is None
    # The operator's warning is only useful if the backoff can also see the failure.
    assert should_skip_for_backoff(session, _digest_settings(), "digest", tick=1) is True


def test_a_crash_while_building_the_digest_still_finishes_a_run(session, monkeypatch, clock):
    """The pending-build phase runs before the Run row is opened; a crash there must not
    vanish from /runs."""
    import jobscout.scheduler as scheduler_module

    _digest_fixture(session)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)

    def _boom(*_a, **_kw):
        raise RuntimeError("no such column: notified_at")

    monkeypatch.setattr(scheduler_module, "select_unnotified", _boom)

    digest_job(session.get_bind(), _digest_settings(digest_hour=0), tick=1)

    assert notifier.sent == [], "nothing was sent, so nothing may be marked"
    run = _digest_run(session)
    assert (run.ok, run.finished_at is None) == (False, False)
    assert "no such column: notified_at" in (run.error or "")
    assert "SENT BUT NOT MARKED" not in (run.error or ""), "no mail went out this time"


def test_a_user_without_an_address_does_not_stop_another_users_digest(session, monkeypatch, clock):
    """The single-user case already pins the skip; this pins that it is a skip and not an
    abort, which is the only way the guard can starve someone else."""
    import jobscout.scheduler as scheduler_module

    wanted = _digest_fixture(session)
    silent = _second_user(session, address=None)
    router = _PerRecipient()
    monkeypatch.setattr(scheduler_module, "build_notifier", router)

    digest_job(session.get_bind(), _digest_settings(digest_hour=0), tick=1)

    assert set(router.by_address) == {"me@example.com"}, "no notifier built for the silent user"
    assert len(router.by_address["me@example.com"].sent) == 1
    session.expire_all()
    notified = {m.user_id: m.notified_at for m in session.exec(select(Match)).all()}
    assert notified[wanted.id] is not None and notified[silent.id] is None
    run = _digest_run(session)
    assert (run.ok, run.counters["users"]) == (True, 1)

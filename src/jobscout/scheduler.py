"""The scheduled half of JobScout. A thin composer over `pipeline/`, like the API and CLI.

Every execution is recorded in a `Run` row, which is also what the failure backoff reads.
The job functions are plain callables so all logic is testable without a scheduler.
"""

import logging
import threading
from datetime import UTC, datetime, timedelta

from apscheduler.job import Job as APSJob
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import Engine
from sqlmodel import Session, col, delete, desc, select

from jobscout.config import Settings
from jobscout.models import Run, User
from jobscout.models.base import utcnow
from jobscout.pipeline.liveness import deactivate_stale_jobs
from jobscout.pipeline.matching import run_match
from jobscout.pipeline.run import run_ingest

log = logging.getLogger(__name__)


def start_run(session: Session, settings: Settings, job: str) -> Run:
    """Open a run and prune expired history in the same transaction.

    The row is written before the work starts and defaults to `ok=False`, so a process
    killed mid-run leaves a trace that reads as a failure rather than vanishing.
    """
    cutoff = utcnow() - timedelta(days=settings.run_retention_days)
    session.exec(delete(Run).where(col(Run.started_at) < cutoff))
    run = Run(job=job)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def finish_run(
    session: Session,
    run: Run,
    ok: bool,
    counters: dict[str, int],
    error: str | None = None,
) -> None:
    run.ok = ok
    run.counters = counters
    run.error = error
    run.finished_at = utcnow()
    session.add(run)
    session.commit()


def should_skip_for_backoff(session: Session, settings: Settings, job: str, tick: int) -> bool:
    """Should this firing be skipped because the job keeps failing?

    Backoff triggers on consecutive failure, not on a 429 specifically: matching a provider's
    rate-limit wording breaks when the wording changes, and it misses the other reasons to
    stop hammering — network, auth, a daily quota. With `k` consecutive failures the job runs
    only every `2**k`-th tick, capped by MAX_BACKOFF_TICKS.

    A skipped tick writes no Run row, so skipping can never deepen the backoff by itself.
    """
    recent = session.exec(
        select(Run)
        .where(col(Run.job) == job)
        .order_by(desc(col(Run.started_at)), desc(col(Run.id)))
        .limit(64)
    ).all()
    failures = 0
    for run in recent:
        if run.ok:
            break
        failures += 1
    if failures == 0:
        return False
    every = 2 ** min(failures, settings.max_backoff_ticks)
    return bool(tick % every != 0)


def ingest_job(engine: Engine, settings: Settings) -> None:
    """Fetch every configured source, then expire what the answering sources stopped showing.

    Total by construction: it never raises, because an exception escaping into the scheduler's
    thread is invisible to the operator. The inner handling records failures on the Run row;
    this outer net covers what cannot be recorded (start_run or finish_run themselves failing).
    """
    try:
        _ingest(engine, settings)
    except Exception:
        log.exception("ingest job crashed outside its own error handling")


def _ingest(engine: Engine, settings: Settings) -> None:
    with Session(engine) as session:
        run = start_run(session, settings, "ingest")
        counters = {"created": 0, "updated": 0, "changed": 0, "deactivated": 0}
        errors: list[str] = []
        succeeded = 0
        deactivated = 0
        try:
            for result in run_ingest(session, settings):
                if result.error is not None:
                    errors.append(f"{result.source}: {result.error}")
                    continue
                succeeded += 1
                counters["created"] += result.created
                counters["updated"] += result.updated
                counters["changed"] += result.changed
                # Only a source that answered may expire its own postings.
                deactivated += deactivate_stale_jobs(session, settings, result.source)
            session.commit()
            # Deactivation lives in this transaction: report it only once it is committed.
            counters["deactivated"] = deactivated
        except Exception as exc:
            session.rollback()
            log.exception("ingest job failed")
            finish_run(
                session, run, ok=False, counters=counters, error=f"{type(exc).__name__}: {exc}"
            )
            return
        # Sources are independent: partial failure is not run failure. Only a run where no source
        # answered counts as failed, otherwise one permanently broken source would drive the
        # consecutive-failure backoff and starve the healthy ones. Errors stay in `error`.
        finish_run(
            session, run, ok=succeeded > 0, counters=counters, error="; ".join(errors) or None
        )


def match_job(engine: Engine, settings: Settings, tick: int = 0) -> None:
    """Score what is pending, for every user, within the per-run caps.

    Never raises, for the same reason as `ingest_job`.
    """
    try:
        _match(engine, settings, tick)
    except Exception:
        log.exception("match job crashed outside its own error handling")


def _match(engine: Engine, settings: Settings, tick: int) -> None:
    with Session(engine) as session:
        if should_skip_for_backoff(session, settings, "match", tick):
            log.info("match job skipped by backoff at tick %s", tick)
            return
        run = start_run(session, settings, "match")
        counters = {
            "candidates": 0,
            "evaluated": 0,
            "skipped_low": 0,
            "embedded": 0,
            "embeddings_pending": 0,
            "errors": 0,
        }
        messages: list[str] = []
        job_errors: list[str] = []
        try:
            user_ids = [uid for uid in session.exec(select(col(User.id))).all() if uid is not None]
            for user_id in user_ids:
                result = run_match(session, settings, user_id)
                counters["candidates"] += result.candidates
                counters["evaluated"] += result.evaluated
                counters["skipped_low"] += result.skipped_low
                counters["embedded"] += result.embedded
                counters["embeddings_pending"] += result.embeddings_pending
                counters["errors"] += len(result.errors)
                job_errors.extend(result.errors)
                if result.error is not None:
                    messages.append(f"user {user_id}: {result.error}")
        except Exception as exc:
            session.rollback()
            log.exception("match job failed")
            finish_run(
                session, run, ok=False, counters=counters, error=f"{type(exc).__name__}: {exc}"
            )
            return
        # A run that hit errors and evaluated nothing accomplished nothing: that is a failure, or
        # the backoff never engages against a rate-limited provider. Partial success stays ok.
        if not messages and counters["errors"] > 0 and counters["evaluated"] == 0:
            messages.append(f"{counters['errors']} error(s), nothing evaluated: {job_errors[0]}")
        finish_run(
            session, run, ok=not messages, counters=counters, error="; ".join(messages) or None
        )


class JobScoutScheduler:
    """Owns the APScheduler instance and the per-job tick counters.

    No persistent jobstore: jobs are registered from Settings at every startup, so a
    schedule from an old configuration can never outlive the configuration that made it.
    """

    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings
        self._scheduler = BackgroundScheduler()
        self._match_tick = 0
        self._tick_lock = threading.Lock()
        # `match` and `match-wake` are different APScheduler ids, so max_instances=1 cannot stop
        # them overlapping. This guard does: start_run writes an ok=False row before the work
        # begins, so an overlapping run would read as a failure to the backoff check.
        self._match_running = threading.Lock()

    def _run_ingest_tick(self) -> None:
        ingest_job(self._engine, self._settings)

    def _next_match_tick(self) -> int:
        with self._tick_lock:
            self._match_tick += 1
            return self._match_tick

    def _run_match_tick(self) -> None:
        # Count every firing, including ones the backoff or the overlap guard skips: otherwise
        # `tick % period` would stay at the same non-zero remainder and never run again.
        tick = self._next_match_tick()
        if not self._match_running.acquire(blocking=False):
            log.warning("match tick %s skipped: another match run is in flight", tick)
            return
        try:
            match_job(self._engine, self._settings, tick=tick)
        finally:
            self._match_running.release()

    def start(self) -> None:
        if not self._settings.scheduler_enabled:
            log.info("scheduler disabled by SCHEDULER_ENABLED")
            return
        jitter = self._settings.scheduler_jitter_seconds
        self._scheduler.add_job(
            self._run_ingest_tick,
            "interval",
            minutes=self._settings.ingest_interval_minutes,
            id="ingest",
            max_instances=1,
            coalesce=True,
            jitter=jitter,
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._run_match_tick,
            "interval",
            minutes=self._settings.match_interval_minutes,
            id="match",
            max_instances=1,
            coalesce=True,
            jitter=jitter,
            replace_existing=True,
        )
        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def get_jobs(self) -> list[APSJob]:
        return list(self._scheduler.get_jobs())

    def wake_matching(self) -> None:
        """Run matching now, out of band. Repeated calls collapse into one pending run."""
        if not self._scheduler.running:
            return
        self._scheduler.add_job(
            self._run_match_tick,
            "date",
            # The one place the project's "timestamps are naive UTC" rule must NOT apply: this
            # value crosses into APScheduler, which localizes a naive datetime into its own
            # timezone. Naive UTC would shift the wake by the machine's UTC offset (hours late in
            # the Americas). Pass an aware value.
            run_date=datetime.now(UTC),
            id="match-wake",
            replace_existing=True,
            misfire_grace_time=None,
        )


def wake_matching(scheduler: "JobScoutScheduler | None") -> None:
    """Ask the scheduler to match now, if there is one. A no-op otherwise.

    The CLI has no scheduler, and the API runs without one when SCHEDULER_ENABLED is false.
    Saving preferences must not fail because of that.
    """
    if scheduler is not None:
        scheduler.wake_matching()

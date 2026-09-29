"""The scheduled half of JobScout. A thin composer over `pipeline/`, like the API and CLI.

Every execution is recorded in a `Run` row, which is also what the failure backoff reads.
The job functions are plain callables so all logic is testable without a scheduler.
"""

import logging
from datetime import timedelta

from sqlmodel import Session, col, delete, desc, select

from jobscout.config import Settings
from jobscout.models import Run
from jobscout.models.base import utcnow

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

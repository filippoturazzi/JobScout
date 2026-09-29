"""The scheduled half of JobScout. A thin composer over `pipeline/`, like the API and CLI.

Every execution is recorded in a `Run` row, which is also what the failure backoff reads.
The job functions are plain callables so all logic is testable without a scheduler.
"""

import logging
from datetime import timedelta

from sqlmodel import Session, col, delete

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

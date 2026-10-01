"""Expiring postings nobody has seen lately. Separate from ingest, which brings data in."""

from datetime import timedelta

from sqlmodel import Session, col, update

from jobscout.config import Settings
from jobscout.models import Job
from jobscout.models.base import utcnow


def deactivate_stale_jobs(session: Session, settings: Settings, source: str) -> int:
    """Mark one source's unseen jobs inactive. Returns the number of rows flipped.

    Scoped to a single source on purpose: the caller passes only sources that answered,
    so a source that is down or was removed from SOURCES never expires its catalogue.
    Does not commit — the caller batches this with its own bookkeeping.
    """
    cutoff = utcnow() - timedelta(days=settings.inactive_after_days)
    result = session.exec(
        update(Job)
        .where(
            col(Job.source) == source,
            col(Job.is_active).is_(True),
            col(Job.last_seen_at) < cutoff,
        )
        .values(is_active=False)
    )
    return result.rowcount

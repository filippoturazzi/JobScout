"""Re-scan history for one user: jobs first seen inside the window that have no fresh match."""

from datetime import timedelta

from sqlmodel import Session

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps
from jobscout.models.base import utcnow
from jobscout.pipeline.matching import MatchRun, run_match


def backfill_matches(
    session: Session,
    settings: Settings,
    user_id: int,
    window_days: int | None = None,
    deps: GraphDeps | None = None,
) -> MatchRun:
    days = window_days if window_days is not None else settings.backfill_window_days
    cutoff = utcnow() - timedelta(days=days)
    return run_match(session, settings, user_id, deps=deps, first_seen_after=cutoff)

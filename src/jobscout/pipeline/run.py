"""Entry points used by the CLI and the API. The only place sources, DB and filters meet."""

from typing import Any

from sqlmodel import Session, col, select, update

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps
from jobscout.matching.llm import MissingProviderError
from jobscout.models import Job, Match, UserPreferences
from jobscout.pipeline.backfill import backfill_matches
from jobscout.pipeline.filters import filter_jobs
from jobscout.pipeline.ingest import IngestResult, ingest
from jobscout.pipeline.matching import MatchRun
from jobscout.pipeline.users import MATCHING_RELEVANT_FIELDS, get_preferences, update_preferences
from jobscout.sources.base import JobSource, SearchQuery
from jobscout.sources.registry import build_sources


def run_ingest(
    session: Session,
    settings: Settings,
    sources: list[JobSource] | None = None,
) -> list[IngestResult]:
    """Instance-global collection. Sources return everything; user filtering happens later."""
    sources = sources if sources is not None else build_sources(settings)
    return ingest(session, sources, SearchQuery())


def list_jobs(
    session: Session,
    user_id: int,
    limit: int = 50,
    apply_filters: bool = True,
    active_only: bool = True,
) -> list[Job]:
    prefs = get_preferences(session, user_id)
    statement = select(Job).order_by(col(Job.first_seen_at).desc(), col(Job.id).desc())
    if active_only:
        statement = statement.where(col(Job.is_active).is_(True))
    jobs = list(session.exec(statement).all())
    if apply_filters:
        jobs = filter_jobs(jobs, prefs)
    return jobs[:limit]


def list_matches(
    session: Session,
    user_id: int,
    min_score: int = 0,
    status: str | None = None,
    limit: int = 50,
) -> list[tuple[Match, Job]]:
    """Scored matches for one user, best first. Inactive jobs and unscored rows are hidden."""
    statement = (
        select(Match, Job)
        .join(Job, col(Match.job_id) == col(Job.id))
        .where(
            col(Match.user_id) == user_id,
            col(Job.is_active).is_(True),
            col(Match.score).is_not(None),
            col(Match.score) >= min_score,
        )
        .order_by(col(Match.score).desc(), col(Match.similarity).desc())
    )
    if status is not None:
        statement = statement.where(col(Match.status) == status)
    return list(session.exec(statement.limit(limit)).all())


def save_preferences(
    session: Session,
    settings: Settings,
    user_id: int,
    changes: dict[str, Any],
    deps: GraphDeps | None = None,
) -> tuple[UserPreferences, MatchRun]:
    """Apply preference changes, invalidate what they affect, and backfill within the cap."""
    prefs, changed = update_preferences(session, user_id, changes)
    if not (changed & MATCHING_RELEVANT_FIELDS):
        return prefs, MatchRun()

    session.exec(
        update(Match)
        .where(col(Match.user_id) == user_id, col(Match.status) != "dismissed")
        .values(status="stale")
    )
    session.commit()
    try:
        run = backfill_matches(session, settings, user_id, deps=deps)
    except MissingProviderError as exc:
        run = MatchRun(error=str(exc))
    return prefs, run

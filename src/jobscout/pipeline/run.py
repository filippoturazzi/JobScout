"""Entry points used by the CLI and the API. The only place sources, DB and filters meet."""

import logging
from collections.abc import Callable
from typing import Any

from sqlmodel import Session, col, select, update
from sqlmodel.sql.expression import Select

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps
from jobscout.models import Job, Match, UserPreferences
from jobscout.pipeline.filters import filter_jobs
from jobscout.pipeline.ingest import IngestResult, ingest
from jobscout.pipeline.matching import MatchRun
from jobscout.pipeline.users import MATCHING_RELEVANT_FIELDS, get_preferences, update_preferences
from jobscout.sources.base import JobSource, SearchQuery
from jobscout.sources.registry import build_sources

log = logging.getLogger(__name__)


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


def match_listing_statement(
    user_id: int, min_score: int = 0, status: str | None = None
) -> Select[tuple[Match, Job]]:
    """The `list_matches` query, separated so a test can compile it for another dialect."""
    statement = (
        select(Match, Job)
        .join(Job, col(Match.job_id) == col(Job.id))
        .where(col(Match.user_id) == user_id, col(Job.is_active).is_(True))
        # SQLite already sorts NULLs last under DESC; Postgres defaults to NULLS FIRST.
        .order_by(col(Match.score).desc().nulls_last(), col(Match.similarity).desc())
    )
    if status is None:
        statement = statement.where(col(Match.score).is_not(None))
    else:
        statement = statement.where(col(Match.status) == status)
    if min_score > 0:
        statement = statement.where(col(Match.score) >= min_score)
    return statement


def list_matches(
    session: Session,
    user_id: int,
    min_score: int = 0,
    status: str | None = None,
    limit: int = 50,
) -> list[tuple[Match, Job]]:
    """Matches for one user, best first (unscored rows last). Inactive jobs are hidden.

    Unscored rows — the `low` ones the cosine prefilter wrote without calling the LLM —
    are hidden from the default listing but returned when an explicit ``status`` is asked
    for, so ``status="low"`` can answer "why didn't this job show up". ``min_score`` is
    applied only when above 0, so the default 0 does not silently drop them again — but
    combining a ``min_score`` above 0 with ``status="low"`` does exclude the unscored
    rows, because a row with no score cannot clear a floor.
    """
    statement = match_listing_statement(user_id, min_score=min_score, status=status)
    return list(session.exec(statement.limit(limit)).all())


def save_preferences(
    session: Session,
    settings: Settings,
    user_id: int,
    changes: dict[str, Any],
    deps: GraphDeps | None = None,
    on_changed: Callable[[], None] | None = None,
) -> tuple[UserPreferences, MatchRun]:
    """Apply preference changes and invalidate what they affect.

    Scoring is the scheduler's job: this stales the affected matches, commits, and asks the
    caller's hook to run matching out of band. Nothing here calls a provider, so a save is
    fast and cannot fail because matching is unavailable. `settings` and `deps` are unused now
    and kept only for signature stability, so callers and tests need not change.
    """
    prefs, changed = update_preferences(session, user_id, changes)
    if not (changed & MATCHING_RELEVANT_FIELDS):
        return prefs, MatchRun()

    session.exec(
        update(Match)
        .where(col(Match.user_id) == user_id, col(Match.status) != "dismissed")
        .values(status="stale")
    )
    session.commit()
    if on_changed is None:
        return prefs, MatchRun()
    try:
        on_changed()
    except Exception as exc:
        # Defensive: the preferences are already committed, so nothing of ours is pending —
        # but `on_changed` is caller code and may have dirtied the session before raising.
        # Without this, its leftovers ride along on the next commit from an unrelated
        # request. Same failure as fd36971, reachable again through the hook.
        session.rollback()
        log.exception("waking the matcher after a preference save failed")
        return prefs, MatchRun(error=f"{type(exc).__name__}: {exc}")
    return prefs, MatchRun()

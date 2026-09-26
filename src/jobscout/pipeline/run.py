"""Entry points used by the CLI and the API. The only place sources, DB and filters meet."""

import logging
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

log = logging.getLogger(__name__)

# `PUT /preferences` runs its backfill inside the HTTP request, so the per-run cap (25 LLM
# calls, 1-2 minutes at real provider latency) would push the response past most proxy and
# client timeouts. Keep a preference save interactive; the real fix is moving the backfill
# onto the stage-3 scheduler, which has no request to block.
_BACKFILL_EVALUATION_CAP = 5


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
    """Matches for one user, best first (unscored rows last). Inactive jobs are hidden.

    Unscored rows — the `low` ones the cosine prefilter wrote without calling the LLM —
    are hidden from the default listing but returned when an explicit ``status`` is asked
    for, so ``status="low"`` can answer "why didn't this job show up". ``min_score`` is
    applied only when above 0, so the default 0 does not silently drop them again.
    """
    statement = (
        select(Match, Job)
        .join(Job, col(Match.job_id) == col(Job.id))
        .where(col(Match.user_id) == user_id, col(Job.is_active).is_(True))
        .order_by(col(Match.score).desc().nulls_last(), col(Match.similarity).desc())
    )
    if status is None:
        statement = statement.where(col(Match.score).is_not(None))
    else:
        statement = statement.where(col(Match.status) == status)
    if min_score > 0:
        statement = statement.where(col(Match.score) >= min_score)
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
    # The preferences are already committed above: from here on, every failure is reported
    # through `MatchRun.error`. Saving preferences must never fail because matching failed.
    try:
        run = backfill_matches(
            session, settings, user_id, deps=deps, limit=_BACKFILL_EVALUATION_CAP
        )
    except MissingProviderError as exc:
        session.rollback()
        run = MatchRun(error=str(exc))
    except Exception as exc:  # 429, network, auth — anything the provider can throw
        session.rollback()
        log.error("backfill after preference save failed: %s: %s", type(exc).__name__, exc)
        run = MatchRun(error=f"{type(exc).__name__}: {exc}")
    return prefs, run

"""Entry points used by the CLI and the API. The only place sources, DB and filters meet."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sqlmodel import Session, col, desc, select, update
from sqlmodel.sql.expression import Select, SelectOfScalar

from jobscout.config import Settings
from jobscout.models import (
    CLOSED_STATUSES,
    USER_STATUSES,
    Job,
    Match,
    Run,
    Search,
    UserPreferences,
)
from jobscout.pipeline.filters import filter_jobs, job_matches_preferences
from jobscout.pipeline.ingest import IngestResult, ingest
from jobscout.pipeline.matching import MatchRun, select_candidates
from jobscout.pipeline.users import MATCHING_RELEVANT_FIELDS, get_preferences, update_preferences
from jobscout.sources.base import JobSource, SearchQuery
from jobscout.sources.registry import build_sources

if TYPE_CHECKING:
    from jobscout.matching.graph import GraphDeps

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
    search_id: int | None,
    limit: int = 50,
    apply_filters: bool = True,
    active_only: bool = True,
) -> list[Job]:
    statement = select(Job).order_by(col(Job.first_seen_at).desc(), col(Job.id).desc())
    if active_only:
        statement = statement.where(col(Job.is_active).is_(True))
    jobs = list(session.exec(statement).all())
    if apply_filters and search_id is not None:  # no search, no preferences to filter by
        prefs = get_preferences(session, search_id)
        jobs = filter_jobs(jobs, prefs)
    return jobs[:limit]


def match_listing_statement(
    search_id: int, min_score: int = 0, status: str | None = None
) -> Select[tuple[Match, Job]]:
    """The `list_matches` query, separated so a test can compile it for another dialect."""
    statement = (
        select(Match, Job)
        .join(Job, col(Match.job_id) == col(Job.id))
        .where(col(Match.search_id) == search_id, col(Job.is_active).is_(True))
        # SQLite already sorts NULLs last under DESC; Postgres defaults to NULLS FIRST.
        .order_by(col(Match.score).desc().nulls_last(), col(Match.similarity).desc())
    )
    if status is None:
        # The user's own verdicts stay out of the default listing, or every search would
        # bring back the jobs they already said no to (or applied for).
        statement = statement.where(
            col(Match.score).is_not(None), col(Match.status).not_in(CLOSED_STATUSES)
        )
    else:
        statement = statement.where(col(Match.status) == status)
    if min_score > 0:
        statement = statement.where(col(Match.score) >= min_score)
    return statement


def list_matches(
    session: Session,
    search_id: int,
    min_score: int = 0,
    status: str | None = None,
    limit: int = 50,
) -> list[tuple[Match, Job]]:
    """Matches for one search, best first (unscored rows last). Inactive jobs are hidden.

    Unscored rows — the `low` ones the cosine prefilter wrote without calling the LLM —
    are hidden from the default listing but returned when an explicit ``status`` is asked
    for, so ``status="low"`` can answer "why didn't this job show up". ``min_score`` is
    applied only when above 0, so the default 0 does not silently drop them again — but
    combining a ``min_score`` above 0 with ``status="low"`` does exclude the unscored
    rows, because a row with no score cannot clear a floor. Dismissed and applied rows are
    hidden the same way, and returned the same way when their status is asked for.

    The default listing also hides jobs the current preferences would no longer select, or a
    narrowed region would keep showing what was scored before. Asking for a status shows them.
    """
    statement = match_listing_statement(search_id, min_score=min_score, status=status)
    if status is not None:
        return list(session.exec(statement.limit(limit)).all())
    prefs = get_preferences(session, search_id)
    rows = session.exec(statement).all()
    return [(match, job) for match, job in rows if job_matches_preferences(job, prefs)][:limit]


def count_waiting(session: Session, search_id: int) -> int:
    """Jobs this search fetched that are still waiting to be scored."""
    return len(select_candidates(session, get_preferences(session, search_id), search_id))


MyJobTab = Literal["all", "saved", "applied"]


@dataclass
class MyJob:
    match: Match
    job: Job
    searches: list[tuple[int, str]]
    """Every search of the user that scored this job, most recently used first."""


@dataclass
class MyJobs:
    items: list[MyJob]
    counts: dict[MyJobTab, int]


def _best_per_job(
    session: Session, user_id: int, tab: MyJobTab, search_id: int | None
) -> list[tuple[Match, Job]]:
    """The user's best-scored match for each active job in the tab, best first."""
    statement = (
        select(Match, Job)
        .join(Job, col(Match.job_id) == col(Job.id))
        .where(col(Match.user_id) == user_id, col(Job.is_active).is_(True))
        .order_by(
            col(Match.score).desc().nulls_last(),
            col(Match.updated_at).desc(),
            col(Match.id).desc(),
        )
    )
    if search_id is not None:
        statement = statement.where(col(Match.search_id) == search_id)
    if tab == "all":
        statement = statement.where(col(Match.score).is_not(None), col(Match.status) != "dismissed")
    else:
        statement = statement.where(col(Match.status) == tab)
    best: dict[int, tuple[Match, Job]] = {}
    for match, job in session.exec(statement).all():
        best.setdefault(match.job_id, (match, job))
    return list(best.values())


def list_my_jobs(
    session: Session,
    user_id: int,
    tab: MyJobTab = "all",
    search_id: int | None = None,
    limit: int = 200,
) -> MyJobs:
    """Every job the user's searches found, once each, at its best score."""
    tabs: tuple[MyJobTab, ...] = ("all", "saved", "applied")
    rows = {t: _best_per_job(session, user_id, t, search_id) for t in tabs}
    counts: dict[MyJobTab, int] = {t: len(rows[t]) for t in tabs}
    shown = rows[tab][:limit]

    job_ids = [job.id for _, job in shown if job.id is not None]
    found_by: dict[int, list[tuple[int, str]]] = {}
    if job_ids:
        named = session.exec(
            select(Match.job_id, Search.id, Search.title)
            .join(Search, col(Match.search_id) == col(Search.id))
            .where(
                col(Match.user_id) == user_id,
                col(Match.job_id).in_(job_ids),
                col(Match.score).is_not(None),
            )
            .order_by(col(Search.last_used_at).desc(), col(Search.id).desc())
        ).all()
        for job_id, found_id, title in named:
            if found_id is not None:
                found_by.setdefault(job_id, []).append((found_id, title))
    items = [MyJob(match, job, found_by.get(match.job_id, [])) for match, job in shown]
    return MyJobs(items=items, counts=counts)


def set_match_status(
    session: Session, user_id: int, match_id: int, status: str
) -> tuple[Match, Job] | None:
    """Record the user's verdict on a job; ``None`` if the match is not theirs.

    A verdict is about the job, so it lands on every match the user has for it, whichever
    search scored it. Returns the requested row.
    """
    if status not in USER_STATUSES:
        raise ValueError(
            f"status {status!r} cannot be set; expected one of {sorted(USER_STATUSES)}"
        )
    row = session.exec(
        select(Match, Job)
        .join(Job, col(Match.job_id) == col(Job.id))
        .where(col(Match.id) == match_id, col(Match.user_id) == user_id)
    ).first()
    if row is None:
        return None
    match, job = row
    session.exec(
        update(Match)
        .where(col(Match.user_id) == user_id, col(Match.job_id) == match.job_id)
        .values(status=status)
    )
    session.commit()
    session.refresh(match)
    return match, job


def run_listing_statement(job: str | None = None) -> SelectOfScalar[Run]:
    """The `list_runs` query, separated so a test can compile it and pin its ordering."""
    # The id tie-break keeps same-timestamp rows newest-first; scheduler.py does the same.
    statement = select(Run).order_by(desc(col(Run.started_at)), desc(col(Run.id)))
    if job is not None:
        statement = statement.where(col(Run.job) == job)
    return statement


def list_runs(session: Session, job: str | None = None, limit: int = 50) -> list[Run]:
    """Scheduled executions, newest first."""
    return list(session.exec(run_listing_statement(job).limit(limit)).all())


def save_preferences(
    session: Session,
    settings: Settings,
    search_id: int,
    changes: dict[str, Any],
    deps: "GraphDeps | None" = None,
    on_changed: Callable[[], None] | None = None,
) -> tuple[UserPreferences, MatchRun]:
    """Apply preference changes and invalidate what they affect.

    Scoring is the scheduler's job: this stales the affected matches, commits, and asks the
    caller's hook to run matching out of band. Nothing here calls a provider, so a save is
    fast and cannot fail because matching is unavailable. `settings` and `deps` are unused now
    and kept only for signature stability, so callers and tests need not change.
    """
    prefs, changed = update_preferences(session, search_id, changes)
    if not (changed & MATCHING_RELEVANT_FIELDS):
        return prefs, MatchRun()

    session.exec(
        update(Match)
        .where(col(Match.search_id) == search_id, col(Match.status).not_in(CLOSED_STATUSES))
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

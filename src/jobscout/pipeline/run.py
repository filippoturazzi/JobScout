"""Entry points used by the CLI and the API. The only place sources, DB and filters meet."""

from sqlmodel import Session, col, select

from jobscout.config import Settings
from jobscout.models import Job, UserPreferences
from jobscout.pipeline.filters import filter_jobs
from jobscout.pipeline.ingest import IngestResult, ingest
from jobscout.pipeline.users import get_preferences
from jobscout.sources.base import JobSource, SearchQuery
from jobscout.sources.registry import build_sources


def build_query(prefs: UserPreferences) -> SearchQuery:
    modes = {m.lower() for m in prefs.work_modes}
    return SearchQuery(
        keywords=list(prefs.titles),
        remote_only=modes == {"remote"},
        locations=list(prefs.regions),
    )


def run_ingest(
    session: Session,
    settings: Settings,
    user_id: int,
    sources: list[JobSource] | None = None,
) -> list[IngestResult]:
    prefs = get_preferences(session, user_id)
    sources = sources if sources is not None else build_sources(settings)
    return ingest(session, sources, build_query(prefs))


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

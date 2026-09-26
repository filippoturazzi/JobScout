"""Entry points used by the CLI and the API. The only place sources, DB and filters meet."""

from sqlmodel import Session, col, select

from jobscout.config import Settings
from jobscout.models import Job
from jobscout.pipeline.filters import filter_jobs
from jobscout.pipeline.ingest import IngestResult, ingest
from jobscout.pipeline.users import get_preferences
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

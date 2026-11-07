"""Saved searches: one profile (its preferences) and one conversation each, per user."""

from sqlmodel import Session, col, delete, desc, select

from jobscout.models import Match, Search, SearchJob, UserPreferences
from jobscout.models.base import utcnow

DEFAULT_SEARCH_TITLE = "My search"


class SearchNotFoundError(LookupError):
    """The search does not exist, or belongs to another user."""


def add_search(session: Session, user_id: int, title: str, paragraph: str = "") -> Search:
    search = Search(user_id=user_id, title=title)
    session.add(search)
    session.flush()
    assert search.id is not None
    session.add(UserPreferences(user_id=user_id, search_id=search.id, profile_summary=paragraph))
    session.commit()
    session.refresh(search)
    return search


def get_search(session: Session, user_id: int, search_id: int) -> Search:
    search = session.get(Search, search_id)
    if search is None or search.user_id != user_id:
        raise SearchNotFoundError(f"No search {search_id} for user_id={user_id}")
    return search


def list_searches(session: Session, user_id: int) -> list[Search]:
    statement = (
        select(Search)
        .where(col(Search.user_id) == user_id)
        .order_by(desc(col(Search.last_used_at)), desc(col(Search.id)))
    )
    return list(session.exec(statement).all())


def latest_search(session: Session, user_id: int) -> Search | None:
    return session.exec(
        select(Search)
        .where(col(Search.user_id) == user_id)
        .order_by(desc(col(Search.last_used_at)), desc(col(Search.id)))
    ).first()


def get_or_create_default_search(session: Session, user_id: int) -> Search:
    search = latest_search(session, user_id)
    if search is None:
        search = add_search(session, user_id, title=DEFAULT_SEARCH_TITLE)
    return search


def default_search_id(session: Session, user_id: int) -> int:
    """The default search's id, for shells that do not take a search yet (temporary)."""
    search_id = get_or_create_default_search(session, user_id).id
    assert search_id is not None, "a persisted search always has an id"
    return search_id


def record_fetched(session: Session, search_id: int, job_ids: list[int]) -> int:
    """Note that this search fetched these jobs. Returns how many pairs were new."""
    wanted = list(dict.fromkeys(job_ids))
    known: set[int] = set()
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        known.update(
            session.exec(
                select(SearchJob.job_id).where(
                    SearchJob.search_id == search_id, col(SearchJob.job_id).in_(chunk)
                )
            ).all()
        )
    new = [job_id for job_id in wanted if job_id not in known]
    session.add_all(SearchJob(search_id=search_id, job_id=job_id) for job_id in new)
    session.commit()
    return len(new)


def touch(session: Session, search: Search) -> None:
    search.last_used_at = utcnow()
    session.add(search)
    session.commit()


def delete_search(session: Session, user_id: int, search_id: int) -> None:
    """Remove a search with its matches, fetched-job links and preferences. The jobs stay."""
    search = get_search(session, user_id, search_id)
    session.exec(delete(Match).where(col(Match.search_id) == search_id))
    session.exec(delete(SearchJob).where(col(SearchJob.search_id) == search_id))
    session.exec(delete(UserPreferences).where(col(UserPreferences.search_id) == search_id))
    session.delete(search)
    session.commit()

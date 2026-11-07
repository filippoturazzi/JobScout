from datetime import timedelta

import pytest
from sqlmodel import select

from jobscout.models import Job, Match, Search, SearchJob, UserPreferences
from jobscout.models.base import utcnow
from jobscout.pipeline.searches import (
    SearchNotFoundError,
    add_search,
    delete_search,
    get_or_create_default_search,
    get_search,
    latest_search,
    list_searches,
    record_fetched,
    touch,
)
from jobscout.pipeline.users import get_or_create_default_user, get_preferences
from tests.helpers import make_search


def _job(session, external_id: str = "j") -> Job:
    job = Job(
        source="t",
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        url="https://x/j",
        description="d",
        content_hash="h",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_add_search_creates_its_preferences(session):
    search = make_search(session, paragraph="AI engineer")
    assert get_preferences(session, search.id).profile_summary == "AI engineer"


def test_latest_search_is_the_most_recently_used(session):
    user = get_or_create_default_user(session)
    older = add_search(session, user.id, "older")
    newer = add_search(session, user.id, "newer")
    assert latest_search(session, user.id).id == newer.id

    older.last_used_at = utcnow() - timedelta(days=1)
    newer.last_used_at = utcnow() - timedelta(days=2)
    session.add_all([older, newer])
    session.commit()
    touch(session, newer)

    assert latest_search(session, user.id).id == newer.id
    assert [s.id for s in list_searches(session, user.id)] == [newer.id, older.id]


def test_latest_search_is_none_without_searches(session):
    user = get_or_create_default_user(session)
    assert latest_search(session, user.id) is None


def test_get_search_refuses_another_users_search(session):
    search = make_search(session)

    with pytest.raises(SearchNotFoundError):
        get_search(session, search.user_id + 1, search.id)
    with pytest.raises(SearchNotFoundError):
        get_search(session, search.user_id, search.id + 1)
    assert get_search(session, search.user_id, search.id).id == search.id


def test_delete_search_removes_its_preferences_and_matches_but_not_jobs(session):
    search = make_search(session, "keep me out")
    other = make_search(session, "stay", title="Other")
    job = _job(session)
    for s in (search, other):
        session.add(Match(job_id=job.id, user_id=s.user_id, search_id=s.id, similarity=0.5))
    record_fetched(session, search.id, [job.id])
    record_fetched(session, other.id, [job.id])
    session.commit()

    delete_search(session, search.user_id, search.id)

    assert session.get(Search, search.id) is None
    assert [p.search_id for p in session.exec(select(UserPreferences)).all()] == [other.id]
    assert [m.search_id for m in session.exec(select(Match)).all()] == [other.id]
    assert [r.search_id for r in session.exec(select(SearchJob)).all()] == [other.id]
    assert session.exec(select(Job)).one().id == job.id


def test_get_or_create_default_search_reuses_the_latest(session):
    user = get_or_create_default_user(session)

    first = get_or_create_default_search(session, user.id)
    second = get_or_create_default_search(session, user.id)

    assert first.id == second.id
    assert len(session.exec(select(Search)).all()) == 1


def test_default_user_has_no_preferences_until_a_search_exists(session):
    user = get_or_create_default_user(session)
    assert session.exec(select(UserPreferences)).all() == []

    add_search(session, user.id, "first")

    assert len(session.exec(select(UserPreferences)).all()) == 1


def test_record_fetched_is_idempotent(session):
    s = make_search(session)
    j1, j2 = _job(session, "j1"), _job(session, "j2")
    assert record_fetched(session, s.id, [j1.id, j2.id]) == 2
    assert record_fetched(session, s.id, [j2.id]) == 0
    assert len(session.exec(select(SearchJob)).all()) == 2

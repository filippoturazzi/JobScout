from datetime import datetime, timedelta

from sqlmodel import select

from jobscout.config import Settings
from jobscout.models import Job, Match, User
from jobscout.pipeline.ingest import upsert_jobs
from jobscout.pipeline.run import list_jobs, list_matches, match_listing_statement, run_ingest
from jobscout.pipeline.users import get_or_create_default_user, update_preferences
from jobscout.sources.base import RawJob, SearchQuery

T0 = datetime(2026, 9, 20, 12, 0, 0)


def raw(external_id, title, remote=True) -> RawJob:
    return RawJob(
        source="fake",
        external_id=external_id,
        title=title,
        company="Acme",
        location="Berlin",
        remote=remote,
        url=f"https://x/{external_id}",
        description="d",
    )


class FakeSource:
    name = "fake"

    def __init__(self, jobs):
        self.jobs = jobs
        self.last_query = None

    def fetch(self, query: SearchQuery):
        self.last_query = query
        return self.jobs


def test_run_ingest_is_global_and_uses_given_sources(session):
    src = FakeSource([raw("a", "AI Engineer")])
    results = run_ingest(session, Settings(_env_file=None), sources=[src])
    assert src.last_query == SearchQuery()
    assert results[0].created == 1


def test_run_ingest_does_not_need_a_user(session):
    results = run_ingest(
        session, Settings(_env_file=None), sources=[FakeSource([raw("a", "AI Engineer")])]
    )

    assert results[0].created == 1
    assert [j.external_id for j in session.exec(select(Job)).all()] == ["a"]
    assert session.exec(select(User)).all() == [], "ingest must not bootstrap a user"


def test_list_jobs_filters_and_orders(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"titles": ["AI Engineer"]})
    upsert_jobs(session, [raw("old", "AI Engineer"), raw("x", "Data Analyst")], now=T0)
    upsert_jobs(session, [raw("new", "Senior AI Engineer")], now=T0 + timedelta(hours=1))

    jobs = list_jobs(session, user.id)
    assert [j.external_id for j in jobs] == ["new", "old"]

    everything = list_jobs(session, user.id, apply_filters=False)
    assert {j.external_id for j in everything} == {"old", "x", "new"}

    assert len(list_jobs(session, user.id, limit=1)) == 1


def test_list_jobs_hides_inactive_by_default(session):
    user = get_or_create_default_user(session)
    upsert_jobs(session, [raw("a", "AI Engineer")], now=T0)
    job = list_jobs(session, user.id)[0]
    job.is_active = False
    session.add(job)
    session.commit()
    assert list_jobs(session, user.id) == []
    assert len(list_jobs(session, user.id, active_only=False)) == 1


def test_list_matches_orders_by_score_and_hides_inactive(session):
    user = get_or_create_default_user(session)
    upsert_jobs(
        session,
        [raw("low", "AI Engineer"), raw("high", "AI Engineer"), raw("gone", "AI Engineer")],
        now=T0,
    )
    jobs = {j.external_id: j for j in session.exec(select(Job)).all()}
    jobs["gone"].is_active = False
    session.add(jobs["gone"])
    session.add(
        Match(job_id=jobs["low"].id, user_id=user.id, similarity=0.5, score=40, status="new")
    )
    session.add(
        Match(job_id=jobs["high"].id, user_id=user.id, similarity=0.8, score=90, status="new")
    )
    session.add(
        Match(job_id=jobs["gone"].id, user_id=user.id, similarity=0.9, score=99, status="new")
    )
    session.commit()

    rows = list_matches(session, user.id)

    assert [job.external_id for _match, job in rows] == ["high", "low"]
    assert len(list_matches(session, user.id, limit=1)) == 1


def test_list_matches_hides_unscored_rows_unless_a_status_is_asked_for(session):
    user = get_or_create_default_user(session)
    upsert_jobs(session, [raw("scored", "AI Engineer"), raw("unscored", "AI Engineer")], now=T0)
    jobs = {j.external_id: j for j in session.exec(select(Job)).all()}
    session.add(
        Match(job_id=jobs["scored"].id, user_id=user.id, similarity=0.7, score=80, status="new")
    )
    session.add(
        Match(job_id=jobs["unscored"].id, user_id=user.id, similarity=0.1, score=None, status="low")
    )
    session.commit()

    default = list_matches(session, user.id)
    assert [job.external_id for _match, job in default] == ["scored"]

    explicit = list_matches(session, user.id, status="low")
    assert [job.external_id for _match, job in explicit] == ["unscored"]
    assert explicit[0][0].score is None


def test_list_matches_orders_unscored_rows_last(session):
    user = get_or_create_default_user(session)
    upsert_jobs(session, [raw("blank", "AI Engineer"), raw("scored", "AI Engineer")], now=T0)
    jobs = {j.external_id: j for j in session.exec(select(Job)).all()}
    session.add(
        Match(job_id=jobs["blank"].id, user_id=user.id, similarity=0.9, score=None, status="stale")
    )
    session.add(
        Match(job_id=jobs["scored"].id, user_id=user.id, similarity=0.1, score=10, status="stale")
    )
    session.commit()

    rows = list_matches(session, user.id, status="stale")

    assert [job.external_id for _match, job in rows] == ["scored", "blank"]


def test_list_matches_spells_nulls_last_for_databases_that_need_it():
    """SQLite already sorts NULLs last under DESC, so only the SQL proves the ordering.

    Postgres defaults DESC to NULLS FIRST and would put the unscored row first, which the
    test above cannot catch on SQLite.
    """
    from sqlalchemy.dialects import postgresql

    statement = match_listing_statement(user_id=1)
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "NULLS LAST" in compiled

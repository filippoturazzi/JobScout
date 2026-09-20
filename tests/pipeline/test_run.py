from datetime import datetime, timedelta

from jobscout.config import Settings
from jobscout.models import UserPreferences
from jobscout.pipeline.ingest import upsert_jobs
from jobscout.pipeline.run import build_query, list_jobs, run_ingest
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


def test_build_query_from_preferences():
    p = UserPreferences(user_id=1, titles=["AI Engineer"], work_modes=["remote"], regions=["DE"])
    q = build_query(p)
    assert q.keywords == ["AI Engineer"]
    assert q.remote_only is True
    assert q.locations == ["DE"]
    assert (
        build_query(UserPreferences(user_id=1, work_modes=["remote", "hybrid"])).remote_only
        is False
    )


def test_run_ingest_uses_prefs_and_given_sources(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"work_modes": ["remote"]})
    src = FakeSource([raw("a", "AI Engineer")])
    results = run_ingest(session, Settings(_env_file=None), user.id, sources=[src])
    assert src.last_query.remote_only is True
    assert results[0].created == 1


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

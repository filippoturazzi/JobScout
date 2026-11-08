from datetime import datetime, timedelta

from sqlmodel import select

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps
from jobscout.models import Job, Match, User
from jobscout.models.base import utcnow
from jobscout.pipeline.ingest import upsert_jobs
from jobscout.pipeline.matching import run_match
from jobscout.pipeline.run import (
    count_waiting,
    list_jobs,
    list_matches,
    list_my_jobs,
    match_listing_statement,
    run_ingest,
    run_listing_statement,
    set_match_status,
)
from jobscout.pipeline.users import update_preferences
from jobscout.sources.base import RawJob, SearchQuery
from tests.helpers import fetched, make_search
from tests.matching.fakes import CountingChatModel, DeterministicFakeEmbedding

T0 = datetime(2026, 9, 20, 12, 0, 0)


def raw(external_id, title, remote=True) -> RawJob:
    return RawJob(
        source="fake",
        external_id=external_id,
        title=title,
        company=f"Acme {external_id}",  # distinct per row, so a test never depends on the merge
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
    search = make_search(session, titles=["AI Engineer"])
    upsert_jobs(session, [raw("old", "AI Engineer"), raw("x", "Data Analyst")], now=T0)
    upsert_jobs(session, [raw("new", "Senior AI Engineer")], now=T0 + timedelta(hours=1))

    jobs = list_jobs(session, search.id)
    assert [j.external_id for j in jobs] == ["new", "old"]

    everything = list_jobs(session, search.id, apply_filters=False)
    assert {j.external_id for j in everything} == {"old", "x", "new"}

    assert len(list_jobs(session, search.id, limit=1)) == 1


def test_list_jobs_hides_inactive_by_default(session):
    search = make_search(session)
    upsert_jobs(session, [raw("a", "AI Engineer")], now=T0)
    job = list_jobs(session, search.id)[0]
    job.is_active = False
    session.add(job)
    session.commit()
    assert list_jobs(session, search.id) == []
    assert len(list_jobs(session, search.id, active_only=False)) == 1


def test_list_matches_orders_by_score_and_hides_inactive(session):
    search = make_search(session)
    upsert_jobs(
        session,
        [raw("low", "AI Engineer"), raw("high", "AI Engineer"), raw("gone", "AI Engineer")],
        now=T0,
    )
    jobs = {j.external_id: j for j in session.exec(select(Job)).all()}
    jobs["gone"].is_active = False
    session.add(jobs["gone"])
    session.add(
        Match(
            job_id=jobs["low"].id,
            user_id=search.user_id,
            search_id=search.id,
            similarity=0.5,
            score=40,
            status="new",
        )
    )
    session.add(
        Match(
            job_id=jobs["high"].id,
            user_id=search.user_id,
            search_id=search.id,
            similarity=0.8,
            score=90,
            status="new",
        )
    )
    session.add(
        Match(
            job_id=jobs["gone"].id,
            user_id=search.user_id,
            search_id=search.id,
            similarity=0.9,
            score=99,
            status="new",
        )
    )
    session.commit()

    rows = list_matches(session, search.id)

    assert [job.external_id for _match, job in rows] == ["high", "low"]
    assert len(list_matches(session, search.id, limit=1)) == 1


def test_list_matches_hides_what_the_preferences_no_longer_select(session):
    search = make_search(session)
    upsert_jobs(session, [raw("kept", "AI Engineer"), raw("closed", "AI Engineer")], now=T0)
    jobs = {j.external_id: j for j in session.exec(select(Job)).all()}
    jobs["closed"].remote = True
    jobs["closed"].location = "United States"
    jobs["kept"].remote = True
    jobs["kept"].location = "Worldwide"
    session.add_all([jobs["closed"], jobs["kept"]])
    session.add(
        Match(
            job_id=jobs["closed"].id,
            user_id=search.user_id,
            search_id=search.id,
            similarity=0.9,
            score=95,
            status="new",
        )
    )
    session.add(
        Match(
            job_id=jobs["kept"].id,
            user_id=search.user_id,
            search_id=search.id,
            similarity=0.5,
            score=60,
            status="new",
        )
    )
    session.commit()
    update_preferences(session, search.id, {"regions": ["Brasil"]})

    assert [job.external_id for _, job in list_matches(session, search.id, limit=1)] == ["kept"]
    assert [job.external_id for _, job in list_matches(session, search.id, status="new")] == [
        "closed",
        "kept",
    ]


def test_list_matches_hides_unscored_rows_unless_a_status_is_asked_for(session):
    search = make_search(session)
    upsert_jobs(session, [raw("scored", "AI Engineer"), raw("unscored", "AI Engineer")], now=T0)
    jobs = {j.external_id: j for j in session.exec(select(Job)).all()}
    session.add(
        Match(
            job_id=jobs["scored"].id,
            user_id=search.user_id,
            search_id=search.id,
            similarity=0.7,
            score=80,
            status="new",
        )
    )
    session.add(
        Match(
            job_id=jobs["unscored"].id,
            user_id=search.user_id,
            search_id=search.id,
            similarity=0.1,
            score=None,
            status="low",
        )
    )
    session.commit()

    default = list_matches(session, search.id)
    assert [job.external_id for _match, job in default] == ["scored"]

    explicit = list_matches(session, search.id, status="low")
    assert [job.external_id for _match, job in explicit] == ["unscored"]
    assert explicit[0][0].score is None


def test_list_matches_orders_unscored_rows_last(session):
    search = make_search(session)
    upsert_jobs(session, [raw("blank", "AI Engineer"), raw("scored", "AI Engineer")], now=T0)
    jobs = {j.external_id: j for j in session.exec(select(Job)).all()}
    session.add(
        Match(
            job_id=jobs["blank"].id,
            user_id=search.user_id,
            search_id=search.id,
            similarity=0.9,
            score=None,
            status="stale",
        )
    )
    session.add(
        Match(
            job_id=jobs["scored"].id,
            user_id=search.user_id,
            search_id=search.id,
            similarity=0.1,
            score=10,
            status="stale",
        )
    )
    session.commit()

    rows = list_matches(session, search.id, status="stale")

    assert [job.external_id for _match, job in rows] == ["scored", "blank"]


def test_list_matches_spells_nulls_last_for_databases_that_need_it():
    """SQLite already sorts NULLs last under DESC, so only the SQL proves the ordering.

    Postgres defaults DESC to NULLS FIRST and would put the unscored row first, which the
    test above cannot catch on SQLite.
    """
    from sqlalchemy.dialects import postgresql

    statement = match_listing_statement(search_id=1)
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "NULLS LAST" in compiled


def test_list_runs_orders_by_started_at_then_id_descending():
    """Only the SQL pins the tie-break: row-order tests depend on which index SQLite picks."""
    from sqlalchemy.dialects import postgresql

    for job in (None, "ingest"):
        statement = run_listing_statement(job)
        compiled = str(statement.compile(dialect=postgresql.dialect()))
        order_by = compiled.split("ORDER BY", 1)[1]

        started_at = order_by.find("started_at DESC")
        run_id = order_by.find(".id DESC")
        assert 0 <= started_at < run_id


def _fake_deps() -> GraphDeps:
    return GraphDeps(
        chat=CountingChatModel(),  # type: ignore[arg-type]
        embed=DeterministicFakeEmbedding(size=8),  # type: ignore[arg-type]
        threshold=-1.0,
        model_name="fake-model",
    )


def _job(session, external_id: str) -> Job:
    upsert_jobs(session, [raw(external_id, "AI Engineer")], now=T0)
    return session.exec(select(Job).where(Job.external_id == external_id)).one()


def _scored(session, search, job: Job, score: int | None, status: str = "new") -> Match:
    match = Match(
        job_id=job.id,
        user_id=search.user_id,
        search_id=search.id,
        similarity=0.8,
        score=score,
        status=status,
    )
    session.add(match)
    session.commit()
    session.refresh(match)
    return match


def test_count_waiting_counts_only_this_searchs_pending_jobs(session):
    mine = make_search(session)
    other = make_search(session, title="Other")
    pending, scored, elsewhere = _job(session, "p"), _job(session, "s"), _job(session, "e")
    fetched(session, mine, pending, scored)
    fetched(session, other, elsewhere)
    _scored(session, mine, scored, 70)

    assert count_waiting(session, mine.id) == 1
    assert count_waiting(session, other.id) == 1


def test_my_jobs_shows_a_job_found_twice_once_at_its_best_score(session):
    a = make_search(session, title="A")
    b = make_search(session, title="B")
    job = _job(session, "x")
    _scored(session, a, job, 60)
    _scored(session, b, job, 85)

    result = list_my_jobs(session, a.user_id)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.match.score == 85
    assert item.job.id == job.id
    assert sorted(item.searches) == [(a.id, "A"), (b.id, "B")]


def test_my_jobs_never_lists_a_match_whose_search_is_gone(session):
    search = make_search(session)
    kept, orphan = _job(session, "kept"), _job(session, "orphan")
    _scored(session, search, kept, 70)
    session.add(
        Match(job_id=orphan.id, user_id=search.user_id, search_id=9999, similarity=0.8, score=95)
    )
    session.add(
        Match(
            job_id=orphan.id,
            user_id=search.user_id,
            search_id=9998,
            similarity=0.8,
            score=90,
            status="saved",
        )
    )
    session.commit()

    result = list_my_jobs(session, search.user_id)

    assert [i.job.id for i in result.items] == [kept.id]
    assert result.counts == {"all": 1, "saved": 0, "applied": 0}


def test_my_jobs_names_searches_by_most_recently_used_first(session):
    a = make_search(session, title="A")
    b = make_search(session, title="B")
    a.last_used_at = utcnow() + timedelta(hours=1)
    session.add(a)
    session.commit()
    job = _job(session, "x")
    _scored(session, a, job, 60)
    _scored(session, b, job, 85)

    assert list_my_jobs(session, a.user_id).items[0].searches == [(a.id, "A"), (b.id, "B")]


def test_my_jobs_best_score_tie_goes_to_the_newest_match(session):
    a = make_search(session, title="A")
    b = make_search(session, title="B")
    job = _job(session, "x")
    _scored(session, a, job, 80)
    newer = _scored(session, b, job, 80)

    assert list_my_jobs(session, a.user_id).items[0].match.id == newer.id


def test_my_jobs_hides_inactive_and_unscored_jobs(session):
    search = make_search(session)
    gone, low, ok = _job(session, "g"), _job(session, "l"), _job(session, "o")
    gone.is_active = False
    session.add(gone)
    session.commit()
    _scored(session, search, gone, 90)
    _scored(session, search, low, None, "low")
    _scored(session, search, ok, 70)

    assert [i.job.id for i in list_my_jobs(session, search.user_id).items] == [ok.id]


def test_my_jobs_tabs_and_counts(session):
    search = make_search(session)
    saved, applied, dismissed, plain = (_job(session, n) for n in ("sv", "ap", "di", "pl"))
    _scored(session, search, saved, 80, "saved")
    _scored(session, search, applied, 70, "applied")
    _scored(session, search, dismissed, 90, "dismissed")
    _scored(session, search, plain, 60)

    everything = list_my_jobs(session, search.user_id)
    assert everything.counts == {"all": 3, "saved": 1, "applied": 1}
    assert [i.job.id for i in everything.items] == [saved.id, applied.id, plain.id]
    assert [i.job.id for i in list_my_jobs(session, search.user_id, "saved").items] == [saved.id]
    assert [i.job.id for i in list_my_jobs(session, search.user_id, "applied").items] == [
        applied.id
    ]


def test_my_jobs_filters_by_search(session):
    a = make_search(session, title="A")
    b = make_search(session, title="B")
    only_a, both = _job(session, "oa"), _job(session, "bo")
    _scored(session, a, only_a, 70)
    _scored(session, a, both, 60)
    _scored(session, b, both, 90, "saved")

    result = list_my_jobs(session, a.user_id, search_id=a.id)

    assert [i.job.id for i in result.items] == [only_a.id, both.id]
    assert result.counts == {"all": 2, "saved": 0, "applied": 0}
    assert sorted(result.items[1].searches) == [(a.id, "A"), (b.id, "B")]


def test_a_verdict_applies_to_every_search_that_found_the_job(session):
    a = make_search(session, title="A")
    b = make_search(session, title="B")
    job = _job(session, "x")
    first = _scored(session, a, job, 60)
    second = _scored(session, b, job, 85)

    row = set_match_status(session, a.user_id, first.id, "dismissed")

    assert row is not None and row[0].id == first.id
    session.refresh(second)
    assert second.status == "dismissed"
    assert list_my_jobs(session, a.user_id).items == []


def test_my_jobs_does_not_resurface_a_dismissed_job_scored_later(session):
    a = make_search(session, "Python LLM engineer.", title="A")
    b = make_search(session, "Python LLM engineer.", title="B")
    job = _job(session, "x")
    other = _job(session, "y")
    first = _scored(session, a, job, 80)
    _scored(session, a, other, 70)
    set_match_status(session, a.user_id, first.id, "dismissed")
    before = list_my_jobs(session, a.user_id).counts
    fetched(session, b, job)

    run_match(session, Settings(_env_file=None, embedding_dim=8), b.id, deps=_fake_deps())

    result = list_my_jobs(session, a.user_id)
    assert [i.job.id for i in result.items] == [other.id]
    assert result.counts == before

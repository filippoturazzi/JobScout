from datetime import datetime, timedelta

from sqlmodel import select

from jobscout.models import Job
from jobscout.pipeline.ingest import content_hash, ingest, upsert_jobs
from jobscout.sources.base import RawJob, SearchQuery

T0 = datetime(2026, 9, 20, 12, 0, 0)


def raw(external_id="j1", title="AI Engineer", description="Build agents.", **kw) -> RawJob:
    data = dict(
        source="test",
        external_id=external_id,
        title=title,
        company="Acme",
        location="Berlin",
        remote=True,
        url=f"https://example.com/{external_id}",
        description=description,
        tags=["python"],
        raw={"id": external_id},
    )
    data.update(kw)
    return RawJob(**data)


def test_content_hash_is_stable_and_sensitive():
    assert content_hash("a", "b") == content_hash("a", "b")
    assert content_hash("a", "b") != content_hash("a", "c")
    assert len(content_hash("a", "b")) == 64


def test_insert_new_jobs(session):
    stats = upsert_jobs(session, [raw("j1"), raw("j2")], now=T0)
    assert (stats.created, stats.updated, stats.changed) == (2, 0, 0)
    jobs = session.exec(select(Job).order_by(Job.external_id)).all()
    assert [j.external_id for j in jobs] == ["j1", "j2"]
    j1 = jobs[0]
    assert j1.first_seen_at == T0 and j1.last_seen_at == T0
    assert j1.is_active is True
    assert j1.content_hash == content_hash("AI Engineer", "Build agents.")
    assert j1.raw == {"id": "j1"}


def test_rerun_same_data_only_touches_last_seen(session):
    upsert_jobs(session, [raw("j1")], now=T0)
    later = T0 + timedelta(hours=1)
    stats = upsert_jobs(session, [raw("j1")], now=later)
    assert (stats.created, stats.updated, stats.changed) == (0, 1, 0)
    j1 = session.exec(select(Job)).one()
    assert j1.first_seen_at == T0
    assert j1.last_seen_at == later
    assert session.exec(select(Job)).all().__len__() == 1


def test_changed_content_updates_text_and_clears_embedding(session):
    upsert_jobs(session, [raw("j1")], now=T0)
    j1 = session.exec(select(Job)).one()
    j1.embedding = b"\x00\x01"
    j1.is_active = False
    session.add(j1)
    session.commit()

    stats = upsert_jobs(session, [raw("j1", description="Build better agents.")], now=T0)
    assert (stats.created, stats.updated, stats.changed) == (0, 0, 1)
    session.refresh(j1)
    assert j1.description == "Build better agents."
    assert j1.embedding is None
    assert j1.content_hash == content_hash("AI Engineer", "Build better agents.")
    assert j1.is_active is True, "a job seen again is active again"


def test_seen_again_reactivates(session):
    upsert_jobs(session, [raw("j1")], now=T0)
    j1 = session.exec(select(Job)).one()
    j1.is_active = False
    session.add(j1)
    session.commit()
    upsert_jobs(session, [raw("j1")], now=T0 + timedelta(days=1))
    session.refresh(j1)
    assert j1.is_active is True


def test_duplicates_within_one_batch_are_collapsed(session):
    stats = upsert_jobs(session, [raw("j1"), raw("j1")], now=T0)
    assert stats.created == 1
    assert len(session.exec(select(Job)).all()) == 1


class FakeSource:
    def __init__(self, name, jobs=None, error=None):
        self.name = name
        self._jobs = jobs or []
        self._error = error

    def fetch(self, query: SearchQuery) -> list[RawJob]:
        if self._error:
            raise self._error
        return self._jobs


def test_ingest_isolates_source_failures(session):
    ok = FakeSource("ok", [raw("a", source="ok")])
    bad = FakeSource("bad", error=RuntimeError("boom"))
    results = ingest(session, [bad, ok], SearchQuery(), now=T0)

    assert [r.source for r in results] == ["bad", "ok"]
    assert results[0].error == "RuntimeError: boom"
    assert results[0].fetched == 0
    assert results[1].error is None
    assert (results[1].fetched, results[1].created) == (1, 1)
    assert len(session.exec(select(Job)).all()) == 1


def test_ingest_isolates_persist_failures_and_keeps_session_usable(session):
    bad = FakeSource("bad", [raw("b1", source="bad", raw={"x": object()})])
    ok = FakeSource("ok", [raw("a1", source="ok")])

    results = ingest(session, [bad, ok], SearchQuery(), now=T0)

    assert results[0].source == "bad"
    assert results[0].error is not None
    assert results[0].fetched == 1
    assert results[1].error is None and results[1].created == 1
    assert [j.external_id for j in session.exec(select(Job)).all()] == ["a1"]


def test_upsert_handles_batches_larger_than_lookup_chunk(session):
    batch = [raw(f"j{i}") for i in range(1200)]
    first = upsert_jobs(session, batch, now=T0)
    second = upsert_jobs(session, batch, now=T0 + timedelta(hours=1))
    assert (first.created, second.updated, second.created) == (1200, 1200, 0)
    assert len(session.exec(select(Job)).all()) == 1200


def test_metadata_is_refreshed_on_every_sighting(session):
    upsert_jobs(session, [raw("j1", location="Berlin", remote=True, tags=["python"])], now=T0)
    j1 = session.exec(select(Job)).one()
    j1.embedding = b"\x01"
    session.add(j1)
    session.commit()

    stats = upsert_jobs(
        session,
        [
            raw(
                "j1",
                location="Munich",
                remote=False,
                tags=["python", "llm"],
                salary_min=60000,
                salary_currency="EUR",
            )
        ],
        now=T0 + timedelta(hours=1),
    )
    session.refresh(j1)
    assert (stats.created, stats.updated, stats.changed) == (0, 1, 0)
    assert j1.location == "Munich" and j1.remote is False
    assert j1.tags == ["python", "llm"] and j1.salary_min == 60000
    assert j1.embedding == b"\x01", "same text: embedding must be kept"
    assert j1.content_hash == content_hash("AI Engineer", "Build agents.")


def test_stats_carry_created_and_changed_ids(session):
    first = upsert_jobs(session, [raw("a"), raw("b")], now=T0)
    ids = {j.external_id: j.id for j in session.exec(select(Job)).all()}
    assert sorted(first.created_ids) == sorted([ids["a"], ids["b"]])
    assert first.changed_ids == []

    second = upsert_jobs(session, [raw("a"), raw("b", description="new text"), raw("c")], now=T0)
    ids = {j.external_id: j.id for j in session.exec(select(Job)).all()}
    assert second.created_ids == [ids["c"]]
    assert second.changed_ids == [ids["b"]]

    third = upsert_jobs(session, [raw("a"), raw("b", description="new text"), raw("c")], now=T0)
    assert (third.created_ids, third.changed_ids) == ([], [])


def test_ingest_result_exposes_ids(session):
    results = ingest(session, [FakeSource("ok", [raw("x", source="ok")])], SearchQuery(), now=T0)
    job_id = session.exec(select(Job)).one().id
    assert results[0].created_ids == [job_id]
    assert results[0].changed_ids == []


def test_changed_jobs_mark_matches_stale_except_dismissed(session):
    from jobscout.models import Match, User

    upsert_jobs(session, [raw("j1"), raw("j2")], now=T0)
    jobs = {j.external_id: j for j in session.exec(select(Job)).all()}
    user_a = User(email="a@b")
    user_b = User(email="b@b")
    session.add(user_a)
    session.add(user_b)
    session.commit()
    session.add(Match(job_id=jobs["j1"].id, user_id=user_a.id, similarity=0.9, status="new"))
    session.add(Match(job_id=jobs["j1"].id, user_id=user_b.id, similarity=0.9, status="dismissed"))
    session.add(Match(job_id=jobs["j2"].id, user_id=user_a.id, similarity=0.9, status="new"))
    session.commit()

    upsert_jobs(session, [raw("j1", description="brand new text"), raw("j2")], now=T0)

    statuses = {(m.job_id, m.user_id): m.status for m in session.exec(select(Match)).all()}
    assert statuses[(jobs["j1"].id, user_a.id)] == "stale"
    assert statuses[(jobs["j1"].id, user_b.id)] == "dismissed"
    assert statuses[(jobs["j2"].id, user_a.id)] == "new", "unchanged job keeps its match"

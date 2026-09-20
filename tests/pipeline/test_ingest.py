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

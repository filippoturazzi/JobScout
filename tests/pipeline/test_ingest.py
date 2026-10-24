from datetime import datetime, timedelta
from unittest.mock import ANY

from sqlmodel import select

from jobscout.models import Job
from jobscout.pipeline.ingest import content_hash, fingerprint, ingest, upsert_jobs
from jobscout.sources.base import RawJob, SearchQuery

T0 = datetime(2026, 9, 20, 12, 0, 0)


def raw(external_id="j1", title="AI Engineer", description="Build agents.", **kw) -> RawJob:
    data = dict(
        source="test",
        external_id=external_id,
        title=title,
        company=f"Acme {external_id}",  # distinct vacancies: same title+company+city would merge
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


def _vacancy(source, external_id, **kw) -> RawJob:
    data = dict(
        source=source,
        external_id=external_id,
        title="Dev Python",
        company="Acme",
        location="São Paulo, SP, BR",
        description=f"<p>the {source} html</p>",
        raw={"description": f"<p>the {source} html</p>"},
    )
    data.update(kw)
    return raw(**data)


def test_fingerprint_normalises_accents_case_spacing_and_location_tail():
    a = fingerprint("Dev  Python", "ACME", "São Paulo, SP, BR")
    assert a == fingerprint("dev python", "Acme", "Sao Paulo, Brazil")
    assert len(a) == 64
    assert a != fingerprint("Dev Python", "Acme", "Rio de Janeiro, RJ, BR")
    assert fingerprint("Dev Python", "Acme", None) == fingerprint("Dev Python", "Acme", "")
    assert fingerprint("Dev Python", "Acme", None) != a


def test_the_same_vacancy_from_two_sources_is_one_row(session):
    upsert_jobs(session, [_vacancy("linkedin", "l1")])
    stats = upsert_jobs(
        session,
        [
            _vacancy(
                "google", "g1", title="dev  python", company="ACME", location="Sao Paulo, Brazil"
            )
        ],
    )
    assert stats.created == 0 and stats.merged == 1
    assert stats.created_ids == []
    [job] = session.exec(select(Job)).all()
    assert job.source == "linkedin"
    assert job.raw["duplicates"] == [{"source": "google", "external_id": "g1", "url": ANY}]
    assert job.raw["duplicates"][0]["url"] == "https://example.com/g1"


def test_a_merge_refreshes_liveness_of_the_first_row(session):
    upsert_jobs(session, [_vacancy("linkedin", "l1")], now=T0)
    job = session.exec(select(Job)).one()
    job.is_active = False
    session.add(job)
    session.commit()
    later = T0 + timedelta(days=1)
    upsert_jobs(session, [_vacancy("google", "g1")], now=later)
    job = session.exec(select(Job)).one()
    assert job.last_seen_at == later
    assert job.is_active is True
    assert job.first_seen_at == T0


def test_the_first_source_payload_is_never_overwritten(session):
    # repair.py re-renders the description from `raw`; a merge must not replace it
    upsert_jobs(session, [_vacancy("linkedin", "l1")])
    upsert_jobs(
        session,
        [_vacancy("google", "g1", description="<p>the google html</p>", url="https://g/1")],
    )
    [job] = session.exec(select(Job)).all()
    assert job.raw["description"] == "<p>the linkedin html</p>"
    assert job.description == "<p>the linkedin html</p>"
    assert job.url == "https://example.com/l1"
    assert job.content_hash == content_hash("Dev Python", "<p>the linkedin html</p>")


def test_duplicates_survive_the_first_source_being_reingested(session):
    upsert_jobs(session, [_vacancy("linkedin", "l1")])
    upsert_jobs(session, [_vacancy("google", "g1")])
    stats = upsert_jobs(session, [_vacancy("linkedin", "l1")])
    assert (stats.created, stats.updated, stats.changed, stats.merged) == (0, 1, 0, 0)
    [job] = session.exec(select(Job)).all()
    assert job.raw["duplicates"] == [{"source": "google", "external_id": "g1", "url": ANY}]
    assert job.raw["description"] == "<p>the linkedin html</p>"


def test_duplicates_survive_a_text_change_of_the_first_source(session):
    upsert_jobs(session, [_vacancy("linkedin", "l1")])
    upsert_jobs(session, [_vacancy("google", "g1")])
    stats = upsert_jobs(session, [_vacancy("linkedin", "l1", description="new text")])
    assert stats.changed == 1
    [job] = session.exec(select(Job)).all()
    assert [d["source"] for d in job.raw["duplicates"]] == ["google"]


def test_a_merged_posting_seen_again_is_not_listed_twice(session):
    upsert_jobs(session, [_vacancy("linkedin", "l1")])
    upsert_jobs(session, [_vacancy("google", "g1")])
    stats = upsert_jobs(session, [_vacancy("google", "g1", url="https://g/new")])
    assert stats.created == 0 and stats.merged == 1
    [job] = session.exec(select(Job)).all()
    assert job.raw["duplicates"] == [
        {"source": "google", "external_id": "g1", "url": "https://g/new"}
    ]


def test_three_sources_in_one_batch_collapse_to_one_row(session):
    stats = upsert_jobs(
        session,
        [_vacancy("linkedin", "l1"), _vacancy("indeed", "i1"), _vacancy("google", "g1")],
    )
    assert (stats.created, stats.merged) == (1, 2)
    [job] = session.exec(select(Job)).all()
    assert [d["source"] for d in job.raw["duplicates"]] == ["indeed", "google"]
    assert stats.created_ids == [job.id]


def test_a_repost_from_the_same_source_stays_two_rows(session):
    # Deliberate trade: the merge is cross-source only. A board relisting a job costs one
    # duplicate row, which beats risking the silent loss of a second real opening.
    upsert_jobs(session, [_vacancy("linkedin", "l1")])
    stats = upsert_jobs(session, [_vacancy("linkedin", "l2")])
    assert (stats.created, stats.merged) == (1, 0)
    assert len(session.exec(select(Job)).all()) == 2


def test_only_a_different_source_lets_a_twin_merge(session):
    upsert_jobs(session, [_vacancy("linkedin", "l1")])
    same = upsert_jobs(session, [_vacancy("linkedin", "l2")])
    other = upsert_jobs(session, [_vacancy("indeed", "i1")])
    assert (same.merged, other.merged) == (0, 1)
    first = session.exec(select(Job).where(Job.external_id == "l1")).one()
    assert [d["source"] for d in first.raw["duplicates"]] == ["indeed"]


def test_the_same_role_in_two_cities_stays_two_rows(session):
    stats = upsert_jobs(
        session,
        [
            _vacancy("linkedin", "l1", location="São Paulo, SP, BR"),
            _vacancy("linkedin", "l2", location="Rio de Janeiro, RJ, BR"),
        ],
    )
    assert stats.created == 2 and stats.merged == 0


def test_a_row_without_a_location_merges_only_with_another_without_one(session):
    upsert_jobs(session, [_vacancy("linkedin", "l1", location=None)])
    with_location = upsert_jobs(session, [_vacancy("indeed", "i1")])
    assert (with_location.created, with_location.merged) == (1, 0)
    without = upsert_jobs(session, [_vacancy("google", "g1", location=None)])
    assert (without.created, without.merged) == (0, 1)
    assert len(session.exec(select(Job)).all()) == 2


def test_rows_with_no_fingerprint_yet_never_merge(session):
    # an existing row written before the fingerprint column (fingerprint IS NULL) is left alone
    upsert_jobs(session, [_vacancy("linkedin", "l1")])
    old = session.exec(select(Job)).one()
    old.fingerprint = None
    session.add(old)
    session.commit()
    stats = upsert_jobs(session, [_vacancy("google", "g1")])
    assert stats.created == 1 and stats.merged == 0
    assert len(session.exec(select(Job)).all()) == 2


def test_a_row_without_a_fingerprint_gets_one_when_seen_again(session):
    upsert_jobs(session, [_vacancy("linkedin", "l1")])
    old = session.exec(select(Job)).one()
    old.fingerprint = None
    session.add(old)
    session.commit()
    upsert_jobs(session, [_vacancy("linkedin", "l1")])
    old = session.exec(select(Job)).one()
    assert old.fingerprint == fingerprint("Dev Python", "Acme", "São Paulo, SP, BR")
    stats = upsert_jobs(session, [_vacancy("google", "g1")])
    assert stats.merged == 1


def test_ingesting_the_same_data_twice_is_still_a_no_op(session):
    upsert_jobs(session, [raw()], now=T0)
    second = upsert_jobs(session, [raw()], now=T0 + timedelta(hours=1))
    assert (second.created, second.changed, second.merged) == (0, 0, 0)
    assert second.updated == 1
    assert session.exec(select(Job)).one().raw == {"id": "j1"}


def test_ingest_result_reports_merged(session):
    class Fixed:
        supports_search = False

        def __init__(self, name, jobs):
            self.name, self._jobs = name, jobs

        def fetch(self, query):
            return self._jobs

    results = ingest(
        session,
        [
            Fixed("linkedin", [_vacancy("linkedin", "l1")]),
            Fixed("google", [_vacancy("google", "g1")]),
        ],
        SearchQuery(),
    )
    assert [(r.created, r.merged) for r in results] == [(1, 0), (0, 1)]

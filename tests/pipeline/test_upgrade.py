import sqlite3
from datetime import datetime

import pytest
from sqlalchemy import make_url
from sqlmodel import Session, select

from jobscout.db import create_engine_from_url, init_db, needs_upgrade
from jobscout.models import Match, Run, Search, SearchJob, UserPreferences
from jobscout.pipeline import upgrade
from jobscout.pipeline.conversation import Conversation, summary
from jobscout.pipeline.upgrade import UpgradeReport, backup_sqlite, upgrade_database


def _upgraded(url: str):
    engine = create_engine_from_url(url)
    report = upgrade_database(engine)
    return engine, report


def test_upgrade_turns_preferences_into_a_first_search(old_db):
    engine, report = _upgraded(old_db)

    assert report == UpgradeReport(searches=1, matches=2, runs=1)
    assert needs_upgrade(engine) is False
    init_db(engine)  # the upgraded database is accepted
    with Session(engine) as session:
        (search,) = session.exec(select(Search)).all()
        (prefs,) = session.exec(select(UserPreferences)).all()
    assert search.user_id == 1
    assert search.title == "Junior AI Engineer"
    conversation = Conversation.model_validate(search.conversation)
    assert conversation.confirmed is True
    assert summary(conversation).work_modes == ["remote"]
    assert summary(conversation).country == "Brazil"
    assert prefs.search_id == search.id
    assert prefs.user_id == 1
    assert prefs.search_terms == ["ai engineer"]
    assert prefs.seniority == ["junior"]
    assert prefs.regions == ["Brazil"]
    assert prefs.required_skills == ["python"]
    assert prefs.profile_summary == "Junior AI engineer, Python, remote from Brazil."
    assert prefs.profile_hash == "hash"
    assert prefs.profile_embedding == b"\x00\x01"
    assert prefs.min_score_to_notify == 75
    assert prefs.notify_email == "me@example.com"


def test_upgrade_names_a_search_without_terms_my_search(old_db):
    connection = sqlite3.connect(make_url(old_db).database or "")
    connection.execute("UPDATE user_preferences SET search_terms = '[]'")
    connection.commit()
    connection.close()

    engine, _ = _upgraded(old_db)

    with Session(engine) as session:
        (search,) = session.exec(select(Search)).all()
    assert search.title == "My search"


def test_upgrade_keeps_matches_with_their_status_and_ids(old_db):
    engine, _ = _upgraded(old_db)

    with Session(engine) as session:
        search = session.exec(select(Search)).one()
        matches = {m.id: m for m in session.exec(select(Match)).all()}
    assert set(matches) == {7, 9}
    assert matches[7].status == "applied"
    assert matches[7].score == 90
    assert matches[7].matched_skills == ["python"]
    assert matches[7].notified_at is None
    assert matches[9].status == "new"
    assert matches[9].score == 80
    assert matches[9].missing_skills == ["go"]
    assert matches[9].notified_at == datetime(2026, 10, 2, 8, 0)
    assert {m.search_id for m in matches.values()} == {search.id}
    assert {m.user_id for m in matches.values()} == {1}


def test_upgrade_scopes_matched_jobs_to_the_search(old_db):
    engine, _ = _upgraded(old_db)

    with Session(engine) as session:
        search = session.exec(select(Search)).one()
        rows = session.exec(select(SearchJob)).all()
    assert {(row.search_id, row.job_id) for row in rows} == {(search.id, 1), (search.id, 2)}


def test_upgrade_links_search_runs(old_db):
    engine, _ = _upgraded(old_db)

    with Session(engine) as session:
        search = session.exec(select(Search)).one()
        runs = {run.id: run for run in session.exec(select(Run)).all()}
    assert runs[1].search_id == search.id
    assert runs[2].search_id is None, "an ingest run belongs to no search"


def test_upgrade_is_a_no_op_on_a_current_database(engine):
    assert upgrade_database(engine) == UpgradeReport(searches=0, matches=0, runs=0)
    with Session(engine) as session:
        assert session.exec(select(Search)).all() == []


def test_upgrade_rolls_back_when_it_fails(old_db, monkeypatch):
    def boom(prefs):
        raise RuntimeError("boom")

    monkeypatch.setattr(upgrade, "from_preferences", boom)
    engine = create_engine_from_url(old_db)

    with pytest.raises(RuntimeError, match="boom"):
        upgrade_database(engine)

    engine.dispose()
    connection = sqlite3.connect(make_url(old_db).database or "")
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master")}
    prefs = connection.execute("SELECT user_id, search_terms FROM user_preferences").fetchall()
    matches = connection.execute('SELECT id, status FROM "match" ORDER BY id').fetchall()
    run_columns = {row[1] for row in connection.execute("PRAGMA table_info(run)")}
    connection.close()
    assert prefs == [(1, '["ai engineer"]')]
    assert matches == [(7, "applied"), (9, "new")]
    assert "search" not in tables
    assert "search_id" not in run_columns
    assert needs_upgrade(create_engine_from_url(old_db)) is True


def test_backup_copies_the_sqlite_file(tmp_path):
    path = tmp_path / "jobscout.db"
    path.write_bytes(b"database bytes")

    backup = backup_sqlite(f"sqlite:///{path}", datetime(2026, 11, 7, 9, 5, 3))

    assert backup == tmp_path / "jobscout.db.bak-20261107-090503"
    assert backup.read_bytes() == b"database bytes"
    assert backup_sqlite("sqlite://", datetime(2026, 11, 7)) is None
    assert backup_sqlite("sqlite:///:memory:", datetime(2026, 11, 7)) is None
    assert backup_sqlite("postgresql://u:p@localhost/jobscout", datetime(2026, 11, 7)) is None

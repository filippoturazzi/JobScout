import json
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, SQLModel

from jobscout.db import create_engine_from_url, init_db

FIXTURES = Path(__file__).parent / "fixtures"


def _test_database_url() -> str | None:
    """`TEST_DATABASE_URL` runs the `engine` fixture on another database (CI: Postgres)."""
    return os.environ.get("TEST_DATABASE_URL") or None


def pytest_runtest_setup(item: pytest.Item) -> None:
    url = _test_database_url()
    if url and not url.startswith("sqlite") and item.get_closest_marker("sqlite_only"):
        pytest.skip("SQLite-specific; TEST_DATABASE_URL points elsewhere")


@pytest.fixture
def engine() -> Iterator[Engine]:
    url = _test_database_url()
    if url is None:
        engine = create_engine_from_url("sqlite://")
        init_db(engine)
        yield engine
        return
    engine = create_engine_from_url(url)
    SQLModel.metadata.drop_all(engine)
    init_db(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _isolate_engines(monkeypatch):
    """Every test starts and ends without cached engines or cached settings.

    The scheduler is disabled by default: otherwise every test that builds the app would
    spawn background threads, and a wake would run the real pipeline on a pool thread.
    """
    from jobscout.config import get_settings
    from jobscout.db import reset_engines

    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    # The developer's own provider config in .env must not reach a test (CI has no .env):
    # an env var outranks .env, and a blank one reads as unset.
    for name in ("LLM_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(name, "")
    reset_engines()
    get_settings.cache_clear()
    yield
    reset_engines()
    get_settings.cache_clear()


_OLD_NOW = "2026-10-01 12:00:00.000000"


@pytest.fixture
def old_db(tmp_path) -> str:
    """The URL of a SQLite file in the shape `main` had before saved searches, with data."""
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.executescript((FIXTURES / "schema_pre_searches.sql").read_text(encoding="utf-8"))
    connection.execute(
        "INSERT INTO user VALUES (1, 'me@example.com', 'en', ?, ?)", (_OLD_NOW, _OLD_NOW)
    )
    connection.execute(
        "INSERT INTO user_preferences (id, user_id, titles, seniority, work_modes, regions,"
        " excluded_regions, min_salary, salary_currency, required_skills, nice_to_have_skills,"
        " excluded_keywords, profile_summary, search_terms, profile_hash, profile_embedding,"
        " min_score_to_notify, notify_email, created_at, updated_at)"
        " VALUES (3, 1, '[]', '[\"junior\"]', '[\"remote\"]', '[\"Brazil\"]', '[]', NULL, NULL,"
        " '[\"python\"]', '[]', '[]', ?, '[\"ai engineer\"]', 'hash', ?, 75,"
        " 'me@example.com', ?, ?)",
        (
            "Junior AI engineer, Python, remote from Brazil.",
            b"\x00\x01",
            _OLD_NOW,
            _OLD_NOW,
        ),
    )
    for job_id in (1, 2):
        connection.execute(
            "INSERT INTO job (id, source, external_id, title, company, location, remote, url,"
            " description, tags, first_seen_at, last_seen_at, is_active, content_hash, raw,"
            " created_at, updated_at) VALUES (?, 'arbeitnow', ?, 'AI Engineer', 'Acme', NULL,"
            " 1, ?, 'Python LLM work.', '[]', ?, ?, 1, 'h', '{}', ?, ?)",
            (job_id, f"ext-{job_id}", f"https://x/{job_id}", *[_OLD_NOW] * 4),
        )
    connection.execute(
        'INSERT INTO "match" (id, job_id, user_id, similarity, score, reasoning,'
        " matched_skills, missing_skills, red_flags, status, llm_model, notified_at,"
        " created_at, updated_at) VALUES (7, 1, 1, 0.8, 90, 'Good.', '[\"python\"]', '[]',"
        " '[]', 'applied', 'fake', NULL, ?, ?)",
        (_OLD_NOW, _OLD_NOW),
    )
    connection.execute(
        'INSERT INTO "match" (id, job_id, user_id, similarity, score, reasoning,'
        " matched_skills, missing_skills, red_flags, status, llm_model, notified_at,"
        " created_at, updated_at) VALUES (9, 2, 1, 0.7, 80, 'Fine.', '[]', '[\"go\"]',"
        " '[]', 'new', 'fake', ?, ?, ?)",
        ("2026-10-02 08:00:00.000000", _OLD_NOW, _OLD_NOW),
    )
    connection.execute(
        "INSERT INTO run (id, job, user_id, started_at, finished_at, ok, error, counters)"
        " VALUES (1, 'search', 1, ?, ?, 1, NULL, '{}')",
        (_OLD_NOW, _OLD_NOW),
    )
    connection.execute(
        "INSERT INTO run (id, job, user_id, started_at, finished_at, ok, error, counters)"
        " VALUES (2, 'ingest', NULL, ?, ?, 1, NULL, '{}')",
        (_OLD_NOW, _OLD_NOW),
    )
    connection.commit()
    connection.close()
    return f"sqlite:///{path}"


def load_jsonl(name: str) -> list[dict]:
    lines = (FIXTURES / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]

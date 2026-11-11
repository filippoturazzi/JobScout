import threading

import pytest

from jobscout.config import Settings
from jobscout.db import (
    DatabaseNeedsUpgradeError,
    create_engine_from_url,
    get_engine,
    init_db,
    needs_upgrade,
    reset_engines,
)


def _settings(url: str) -> Settings:
    return Settings(_env_file=None, database_url=url)


def test_same_url_returns_same_engine(tmp_path):
    s = _settings(f"sqlite:///{tmp_path / 'a.db'}")
    assert get_engine(s) is get_engine(s)


def test_different_urls_return_different_engines(tmp_path):
    a = get_engine(_settings(f"sqlite:///{tmp_path / 'a.db'}"))
    b = get_engine(_settings(f"sqlite:///{tmp_path / 'b.db'}"))
    assert a is not b


def test_reset_engines_yields_fresh_instance(tmp_path):
    s = _settings(f"sqlite:///{tmp_path / 'a.db'}")
    before = get_engine(s)
    reset_engines()
    assert get_engine(s) is not before


def test_get_engine_defaults_to_settings(monkeypatch, tmp_path):
    import jobscout.db as db

    monkeypatch.setattr(db, "get_settings", lambda: _settings(f"sqlite:///{tmp_path / 'd.db'}"))
    assert str(get_engine().url).endswith("d.db")


def test_get_engine_returns_one_engine_under_concurrent_callers():
    """The scheduler thread and a request can race here; two StaticPool engines
    would be two different in-memory databases, not just a wasted pool."""
    reset_engines()
    settings = Settings(_env_file=None, database_url="sqlite://")
    engines = []
    barrier = threading.Barrier(8)

    def grab():
        barrier.wait()
        engines.append(get_engine(settings))

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(engines) == 8  # a thread that died inside get_engine must not pass silently
    assert len({id(engine) for engine in engines}) == 1


def test_needs_upgrade_detects_the_old_shape(old_db, engine):
    assert needs_upgrade(create_engine_from_url(old_db)) is True
    assert needs_upgrade(engine) is False


def test_init_db_refuses_an_old_database(old_db):
    with pytest.raises(DatabaseNeedsUpgradeError, match="upgrade-db"):
        init_db(create_engine_from_url(old_db))


def _without_sources_column(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE run DROP COLUMN sources"))


def test_needs_upgrade_when_run_has_no_sources_column(tmp_path):
    engine = create_engine_from_url(f"sqlite:///{tmp_path / 'a.db'}")
    init_db(engine)
    assert needs_upgrade(engine) is False
    _without_sources_column(engine)
    assert needs_upgrade(engine) is True
    with pytest.raises(DatabaseNeedsUpgradeError, match="upgrade-db"):
        init_db(engine)


def test_a_server_database_survives_its_restart():
    """A restarted Postgres leaves dead pooled connections; pre-ping replaces them before use
    instead of failing the next request or scheduled run. No connection is opened here."""
    engine = create_engine_from_url("postgresql+psycopg://u:p@localhost:5432/db")
    assert engine.pool._pre_ping is True

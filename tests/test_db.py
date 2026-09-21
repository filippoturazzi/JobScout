from jobscout.config import Settings
from jobscout.db import get_engine, reset_engines


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

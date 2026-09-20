from jobscout.config import Settings, get_settings


def test_defaults_work_without_env():
    s = Settings(_env_file=None)
    assert s.database_url == "sqlite:///./jobscout.db"
    assert s.source_names == ["arbeitnow"]
    assert s.arbeitnow_max_pages == 2
    assert s.inactive_after_days == 14
    assert s.backfill_window_days == 30


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("SOURCES", "arbeitnow, remoteok ,")
    monkeypatch.setenv("ARBEITNOW_MAX_PAGES", "5")
    s = Settings(_env_file=None)
    assert s.database_url == "sqlite://"
    assert s.source_names == ["arbeitnow", "remoteok"]
    assert s.arbeitnow_max_pages == 5


def test_get_settings_is_cached():
    get_settings.cache_clear()
    assert get_settings() is get_settings()

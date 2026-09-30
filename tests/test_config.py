from jobscout.config import Settings, get_settings


def test_defaults_work_without_env():
    s = Settings(_env_file=None)
    assert s.database_url == "sqlite:///./jobscout.db"
    assert s.source_names == ["arbeitnow"]
    assert s.arbeitnow_max_pages == 2
    assert s.inactive_after_days == 14


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


def test_matching_defaults():
    s = Settings(_env_file=None)
    assert s.llm_provider == "google"
    assert s.llm_model == "gemini-3.5-flash"
    assert s.embedding_model == "gemini-embedding-2"
    assert s.embedding_dim == 768
    assert s.similarity_threshold == 0.45
    # Sized to the free tier's ~30k embedding tokens/min: the vector is built from the
    # short `job_embedding_text` (~175 tokens), not the full posting. See matching.py.
    assert s.max_embeddings_per_run == 100
    assert s.max_llm_evaluations_per_run == 25


def test_matching_settings_from_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "0.5")
    monkeypatch.setenv("MAX_LLM_EVALUATIONS_PER_RUN", "3")
    s = Settings(_env_file=None)
    assert s.llm_provider == "ollama"
    assert s.similarity_threshold == 0.5
    assert s.max_llm_evaluations_per_run == 3


def test_scheduler_settings_have_operator_defaults(monkeypatch):
    monkeypatch.delenv("SCHEDULER_ENABLED")  # conftest disables it for the whole suite
    settings = Settings(_env_file=None)

    assert settings.scheduler_enabled is True
    assert settings.ingest_interval_minutes == 60
    assert settings.match_interval_minutes == 15
    assert settings.scheduler_jitter_seconds == 30
    assert settings.run_retention_days == 30
    assert settings.max_backoff_ticks == 6


def test_scheduler_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    assert Settings(_env_file=None).scheduler_enabled is False

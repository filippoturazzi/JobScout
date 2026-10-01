import pytest
from pydantic import ValidationError

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
    monkeypatch.delenv(
        "SCHEDULER_ENABLED", raising=False
    )  # conftest disables it for the whole suite
    settings = Settings(_env_file=None)

    assert settings.scheduler_enabled is True
    assert settings.ingest_interval_minutes == 60
    assert settings.match_interval_minutes == 15
    assert settings.scheduler_jitter_seconds == 30
    assert settings.run_retention_days == 30
    assert settings.max_backoff_ticks == 6


def test_scheduler_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "true")
    assert Settings(_env_file=None).scheduler_enabled is True

    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    assert Settings(_env_file=None).scheduler_enabled is False


def test_log_level_is_case_insensitive():
    assert Settings(_env_file=None, log_level="info").log_level == "INFO"


@pytest.mark.parametrize("bad", ["chatty", "", "20"])
def test_invalid_log_level_names_the_valid_values(bad):
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, log_level=bad)

    message = str(excinfo.value)
    assert "WARNING" in message and "CRITICAL" in message


@pytest.mark.parametrize("name", ["ingest_interval_minutes", "match_interval_minutes"])
@pytest.mark.parametrize("bad", [0, -5])
def test_intervals_below_one_minute_are_rejected(name, bad):
    """0 would be coerced by APScheduler into a one-second interval against a public API."""
    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None, **{name: bad})

    assert name in str(excinfo.value)
    assert "greater than or equal to 1" in str(excinfo.value)


@pytest.mark.parametrize(
    "name", ["scheduler_jitter_seconds", "run_retention_days", "max_backoff_ticks"]
)
def test_counters_reject_negatives_but_accept_zero(name):
    assert getattr(Settings(_env_file=None, **{name: 0}), name) == 0
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{name: -1})


def test_valid_intervals_are_accepted():
    s = Settings(_env_file=None, ingest_interval_minutes=1, match_interval_minutes=240)

    assert (s.ingest_interval_minutes, s.match_interval_minutes) == (1, 240)


def test_intervals_parse_as_integers_from_the_environment(monkeypatch):
    monkeypatch.setenv("INGEST_INTERVAL_MINUTES", "120")
    monkeypatch.setenv("MATCH_INTERVAL_MINUTES", "5")

    s = Settings(_env_file=None)

    assert (s.ingest_interval_minutes, s.match_interval_minutes) == (120, 5)


def test_an_interval_of_zero_from_the_environment_is_rejected(monkeypatch):
    monkeypatch.setenv("INGEST_INTERVAL_MINUTES", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)

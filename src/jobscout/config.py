"""Operator configuration, read from environment variables or a .env file.

Anything that describes *who runs this instance* (database, enabled sources, intervals,
provider keys) belongs here. Anything that describes *what a user wants* belongs in
``UserPreferences`` — never here.
"""

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./jobscout.db"
    sources: str = "himalayas,remotive,linkedin,indeed"
    arbeitnow_max_pages: int = 2
    inactive_after_days: int = 14

    # --- Scheduler (stage 3) ---
    # Off by default: a fresh clone must not spend LLM quota on a schedule nobody asked for.
    scheduler_enabled: bool = False
    # ge=1: APScheduler coerces a 0-minute interval into one second, which would hammer a
    # keyless public API. A typo must stop the process, not start a 1 Hz fetch loop.
    ingest_interval_minutes: int = Field(default=60, ge=1)
    match_interval_minutes: int = Field(default=15, ge=1)
    scheduler_jitter_seconds: int = Field(default=30, ge=0)
    run_retention_days: int = Field(default=30, ge=0)
    max_backoff_ticks: int = Field(default=6, ge=0)

    # --- Notifications (stage 4) ---
    # SMTP credentials identify who runs the instance, so they are operator config.
    # The recipient address is a user preference — that is what lets a hosted demo
    # work without the operator registering anyone.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    # Local hour (server timezone) at or after which the daily digest is sent.
    digest_hour: int = Field(default=9, ge=0, le=23)
    # The digest job polls at this interval; that is also its retry cadence, which is
    # why there is no separate retry setting.
    digest_interval_minutes: int = Field(default=60, ge=1)

    # --- Scraped sources via python-jobspy (stage 5) ---
    # A proxy is optional and usually paid. Without one, the volumes below are what keeps a
    # clone from being rate-limited or blocked by LinkedIn and Indeed.
    # Comma-separated, each entry `user:pass@host:port` or a bare host.
    jobspy_proxies: str | None = None
    # Postings fetched per search term. Kept small: every term is one scrape.
    jobspy_results_wanted: int = Field(default=10, ge=1)
    # Search terms per run. Caps how many scrapes one run performs.
    jobspy_max_terms: int = Field(default=3, ge=1)
    # Only postings from the last N hours. 168 is one week, a comfortable window for a daily run.
    jobspy_hours_old: int = Field(default=168, ge=1)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "WARNING"

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalise_log_level(cls, value: Any) -> Any:
        # Accept `info`; anything else is rejected with the valid names, never silently
        # replaced, so a typo cannot hide the output the operator asked for.
        return value.strip().upper() if isinstance(value, str) else value

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    # One key for the chat model, whichever provider issued it: the provider is read from the
    # key's prefix (see matching/llm.py) unless LLM_PROVIDER names it, and LLM_MODEL defaults
    # to a cheap model of that provider.
    llm_api_key: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    # Embeddings default to Gemini whatever runs the chat: its free tier is bounded per
    # minute, not per day, and most chat providers (Groq, DeepSeek, Anthropic) have none.
    embedding_provider: str = "google"
    embedding_model: str | None = None
    embedding_dim: int = 768
    # Live run 2026-09-25 (30 active jobs, profile "Junior AI engineer... Python, FastAPI,
    # LLM applications, LangGraph. Remote, Europe."): observed cosine similarity ranged
    # 0.503-0.695, so the old 0.35 floor never fired. No clean gap between plainly-relevant
    # and plainly-irrelevant titles showed up at this sample size (e.g. "Account Executive"
    # and "RevOps" postings scored 0.62-0.63, close to the one genuine "AI Engineer" match at
    # 0.695), so raised conservatively into the gap between 0.35 and the observed floor,
    # leaving margin below every score seen so far.
    similarity_threshold: float = 0.45
    # Bounded by the provider's daily quota: Gemini's free tier allows 20 requests a day
    # (2026-10), and a search spends one more call extracting its terms. A run that hits the
    # quota anyway stops scoring and leaves the rest for the next run.
    max_llm_evaluations_per_run: int = 15
    # Bounded by the provider's per-minute token budget, not by cost alone: see the
    # measurement above _EMBED_CHUNK in pipeline/matching.py before raising this.
    # 100 jobs x ~175 tokens is ~18k, inside the free tier's ~30k/min.
    max_embeddings_per_run: int = 100
    # Provider-specific keys. GOOGLE_API_KEY is what Gemini embeddings use; both also serve
    # as the chat key when LLM_API_KEY is empty (how .env files written before it worked).
    google_api_key: str | None = None
    openai_api_key: str | None = None

    @field_validator(
        "llm_api_key",
        "llm_provider",
        "llm_model",
        "embedding_model",
        "google_api_key",
        "openai_api_key",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        # `.env.example` ships `LLM_API_KEY=`: an empty line means "not set", not "".
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @property
    def source_names(self) -> list[str]:
        return [name.strip() for name in self.sources.split(",") if name.strip()]

    @property
    def jobspy_proxy_list(self) -> list[str]:
        if not self.jobspy_proxies:
            return []
        return [entry.strip() for entry in self.jobspy_proxies.split(",") if entry.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Operator configuration, read from environment variables or a .env file.

Anything that describes *who runs this instance* (database, enabled sources, intervals,
provider keys) belongs here. Anything that describes *what a user wants* belongs in
``UserPreferences`` — never here.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./jobscout.db"
    sources: str = "arbeitnow"
    arbeitnow_max_pages: int = 2
    inactive_after_days: int = 14
    backfill_window_days: int = 30
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    llm_provider: str = "google"
    llm_model: str = "gemini-3.5-flash"
    embedding_model: str = "gemini-embedding-2"
    embedding_dim: int = 768
    # Live run 2026-09-25 (30 active jobs, profile "Junior AI engineer... Python, FastAPI,
    # LLM applications, LangGraph. Remote, Europe."): observed cosine similarity ranged
    # 0.503-0.695, so the old 0.35 floor never fired. No clean gap between plainly-relevant
    # and plainly-irrelevant titles showed up at this sample size (e.g. "Account Executive"
    # and "RevOps" postings scored 0.62-0.63, close to the one genuine "AI Engineer" match at
    # 0.695), so raised conservatively into the gap between 0.35 and the observed floor,
    # leaving margin below every score seen so far.
    similarity_threshold: float = 0.45
    max_llm_evaluations_per_run: int = 25
    # Bounded by the provider's per-minute token budget, not by cost alone: see the
    # measurement above _EMBED_CHUNK in pipeline/matching.py before raising this.
    # 100 jobs x ~175 tokens is ~18k, inside the free tier's ~30k/min.
    max_embeddings_per_run: int = 100
    google_api_key: str | None = None
    openai_api_key: str | None = None

    @property
    def source_names(self) -> list[str]:
        return [name.strip() for name in self.sources.split(",") if name.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

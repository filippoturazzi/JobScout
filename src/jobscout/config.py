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

    @property
    def source_names(self) -> list[str]:
        return [name.strip() for name in self.sources.split(",") if name.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

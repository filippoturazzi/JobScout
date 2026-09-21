"""Contracts every job source implements. Sources know nothing about the database."""

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class SearchQuery(BaseModel):
    """What the pipeline asks a source for, derived from user preferences."""

    keywords: list[str] = Field(default_factory=list)
    remote_only: bool = False
    locations: list[str] = Field(default_factory=list)


class RawJob(BaseModel):
    """A normalized posting as returned by a source, before persistence."""

    source: str
    external_id: str
    title: str
    company: str
    location: str | None = None
    remote: bool = False
    url: str
    description: str
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    tags: list[str] = Field(default_factory=list)
    posted_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class JobSource(Protocol):
    """A job source. Sources must return everything they fetched; never drop results
    based on ``query``. ``SearchQuery`` only parameterizes APIs that require server-side
    search. User filtering happens in ``pipeline/filters.py``.
    """

    name: str

    def fetch(self, query: SearchQuery) -> list[RawJob]:
        """Fetch postings from the source. Must return everything fetched; never drop
        results based on ``query``. ``SearchQuery`` only parameterizes APIs that require
        server-side search. User filtering happens in ``pipeline/filters.py``.
        """
        ...

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from jobscout.models.base import utcnow


class Job(SQLModel, table=True):
    """A posting as seen on a source. Global: shared by all users."""

    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_job_source_external_id"),)

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    external_id: str = Field(index=True)
    title: str
    company: str
    location: str | None = None
    remote: bool = Field(default=False)
    url: str
    description: str
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    posted_at: datetime | None = None
    first_seen_at: datetime = Field(default_factory=utcnow, nullable=False)
    last_seen_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
    is_active: bool = Field(default=True, index=True)
    content_hash: str
    embedding: bytes | None = None
    raw: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=utcnow, nullable=False, sa_column_kwargs={"onupdate": utcnow}
    )

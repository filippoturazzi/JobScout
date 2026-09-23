from datetime import datetime

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from jobscout.models.base import utcnow

MATCH_STATUSES: frozenset[str] = frozenset(
    {"new", "seen", "saved", "dismissed", "notified", "low", "stale"}
)
"""Low = rejected by cosine prefilter; stale = needs re-evaluation."""

REEVALUATABLE_STATUSES: frozenset[str] = frozenset({"stale"})
"""Statuses a new run may pick up again. `dismissed` is deliberately absent."""


class Match(SQLModel, table=True):
    """One evaluated (job, user) pair."""

    __table_args__ = (UniqueConstraint("job_id", "user_id", name="uq_match_job_user"),)

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    similarity: float
    score: int | None = None
    reasoning: str | None = None
    matched_skills: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    missing_skills: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    red_flags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    status: str = Field(default="new", index=True)
    llm_model: str | None = None
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=utcnow, nullable=False, sa_column_kwargs={"onupdate": utcnow}
    )

from datetime import datetime

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from jobscout.models.base import utcnow

MATCH_STATUSES: frozenset[str] = frozenset(
    {"new", "seen", "saved", "dismissed", "notified", "low", "stale"}
)
"""`low` = rejected by the cosine prefilter, terminal until something stales it;
`stale` = needs re-evaluation; `dismissed` = the user said no, and it sticks."""

REEVALUATABLE_STATUSES: frozenset[str] = frozenset({"stale"})
"""Statuses a new run may pick up again. `low` is not one — only a stale-ing event
(a changed job hash, a changed preference) puts a rejected pair back in the queue —
and `dismissed` is deliberately absent, so a dismissal is never re-evaluated."""


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

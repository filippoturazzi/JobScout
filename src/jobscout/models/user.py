from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from jobscout.models.base import utcnow


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    locale: str = Field(default="en")
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=utcnow, nullable=False, sa_column_kwargs={"onupdate": utcnow}
    )


class UserPreferences(SQLModel, table=True):
    """What one user is looking for. Source of truth for filtering and (later) matching."""

    __tablename__ = "user_preferences"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True, index=True)
    titles: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    seniority: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    work_modes: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    regions: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    min_salary: int | None = None
    salary_currency: str | None = None
    required_skills: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    nice_to_have_skills: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    excluded_keywords: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    profile_summary: str = Field(default="")
    profile_embedding: bytes | None = None
    min_score_to_notify: int = Field(default=70)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=utcnow, nullable=False, sa_column_kwargs={"onupdate": utcnow}
    )


PROTECTED_PREFERENCE_FIELDS: frozenset[str] = frozenset(
    {"id", "user_id", "created_at", "updated_at", "profile_embedding"}
)


def non_nullable_preference_fields() -> frozenset[str]:
    """User-editable preference columns that must never be set to NULL."""
    table = UserPreferences.__table__  # Task 7 adds a narrow type-ignore here only if mypy asks
    return frozenset(
        column.name
        for column in table.columns
        if not column.nullable and column.name not in PROTECTED_PREFERENCE_FIELDS
    )

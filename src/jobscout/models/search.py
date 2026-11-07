from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from jobscout.models.base import utcnow


class Search(SQLModel, table=True):
    """One saved search: a profile (its `UserPreferences`) and the conversation behind it."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    title: str
    conversation: dict[str, Any] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    last_used_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=utcnow, nullable=False, sa_column_kwargs={"onupdate": utcnow}
    )

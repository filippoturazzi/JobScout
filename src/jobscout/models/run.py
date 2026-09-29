from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from jobscout.models.base import utcnow

RUN_JOBS: frozenset[str] = frozenset({"ingest", "match"})
"""The scheduled jobs that record a run. Stage 4 adds the notifier."""


class Run(SQLModel, table=True):
    """One execution of one scheduled job.

    The row is created before the work starts and finished afterwards, so `ok=False` with
    no `finished_at` is what a killed process leaves behind. `counters` is a JSON blob
    because the two jobs report different things.
    """

    id: int | None = Field(default=None, primary_key=True)
    job: str = Field(index=True)
    started_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
    finished_at: datetime | None = None
    ok: bool = False
    error: str | None = None
    counters: dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))

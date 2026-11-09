from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from jobscout.models.base import utcnow

RUN_JOBS: frozenset[str] = frozenset({"ingest", "match", "digest", "search"})
"""Every job that records a run. `search` is user-initiated; the other three are scheduled."""


class Run(SQLModel, table=True):
    """One execution of one scheduled job.

    The row is created before the work starts and finished afterwards, so `ok=False` with
    no `finished_at` is what a killed process leaves behind. `counters` is a JSON blob
    because each job reports different things.
    """

    id: int | None = Field(default=None, primary_key=True)
    job: str = Field(index=True)
    # Null for the instance-global jobs (ingest, match, digest); set for a search, which is
    # always one user's. Indexed because the only query on it is "this user's run in flight".
    user_id: int | None = Field(default=None, index=True)
    # Set for a search run; no foreign key, so the history outlives a deleted search.
    search_id: int | None = Field(default=None, index=True)
    started_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
    finished_at: datetime | None = None
    ok: bool = False
    error: str | None = None
    counters: dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    # A search run's per-source progress, in run order: name, state (waiting, searching, done,
    # failed, skipped), fetched, queries_done, queries_total, detail, notes (what it could not
    # do without failing; absent from older rows). Empty for every other job
    # and for a ranking run, which fetches nothing. Reassigned, never mutated: a changed JSON
    # value is not marked dirty.
    sources: list[dict[str, object]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )

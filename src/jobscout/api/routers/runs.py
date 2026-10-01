from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from jobscout.api.deps import get_session
from jobscout.api.schemas import RunRead
from jobscout.models import RUN_JOBS
from jobscout.pipeline.run import list_runs

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunRead])
def read_runs(
    session: Annotated[Session, Depends(get_session)],
    job: Annotated[str | None, Query(description="Filter by job name: ingest or match.")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RunRead]:
    """Scheduled executions, newest first. Instance-wide, not per user."""
    if job is not None and job not in RUN_JOBS:
        raise HTTPException(
            status_code=422, detail=f"unknown job {job!r}; expected one of {sorted(RUN_JOBS)}"
        )
    return [RunRead.model_validate(run) for run in list_runs(session, job=job, limit=limit)]

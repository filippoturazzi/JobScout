from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from jobscout.api.deps import get_current_user_id, get_session
from jobscout.api.schemas import JobRead
from jobscout.pipeline.run import list_jobs
from jobscout.pipeline.searches import get_search, latest_search

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobRead])
def read_jobs(
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
    search_id: Annotated[
        int | None,
        Query(description="Filter by this search's preferences; default is the latest search."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    all: Annotated[bool, Query(description="Ignore preferences; return every active job.")] = False,
) -> list[JobRead]:
    """Active jobs. With no search at all, every active job, unfiltered."""
    if search_id is not None:
        get_search(session, user_id, search_id)
    else:
        latest = latest_search(session, user_id)
        search_id = latest.id if latest is not None else None
    jobs = list_jobs(session, search_id, limit=limit, apply_filters=not all)
    return [JobRead.model_validate(j) for j in jobs]

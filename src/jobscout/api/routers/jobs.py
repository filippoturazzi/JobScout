from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from jobscout.api.deps import get_current_user_id, get_session
from jobscout.api.schemas import JobRead
from jobscout.pipeline.run import list_jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobRead])
def read_jobs(
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    all: Annotated[bool, Query(description="Ignore preferences; return every active job.")] = False,
) -> list[JobRead]:
    jobs = list_jobs(session, user_id, limit=limit, apply_filters=not all)
    return [JobRead.model_validate(j) for j in jobs]

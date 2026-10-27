from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from jobscout.api.deps import get_current_user_id, get_session
from jobscout.api.schemas import RunRead, SearchStarted
from jobscout.models import Run

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", status_code=202, response_model=SearchStarted)
def start_search(
    request: Request, user_id: Annotated[int, Depends(get_current_user_id)]
) -> SearchStarted:
    """Start a search in the background, or return the one already in flight for this user.

    Poll ``GET /search/{run_id}`` for its progress.
    """
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="no scheduler to run the search on")
    return SearchStarted(run_id=scheduler.start_search(user_id))


@router.get("/{run_id}", response_model=RunRead)
def read_search(
    run_id: int,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> RunRead:
    """One search run with its counters, which are written while it is still going."""
    run = session.get(Run, run_id)
    if run is None or run.job != "search" or run.user_id != user_id:
        raise HTTPException(status_code=404, detail=f"no search run {run_id}")
    return RunRead.model_validate(run)

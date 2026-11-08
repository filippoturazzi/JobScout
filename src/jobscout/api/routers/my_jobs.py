from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from jobscout.api.deps import get_current_user_id, get_session
from jobscout.api.routers.matches import read_match
from jobscout.api.schemas import MyJobRead, MyJobsRead, SearchTitle
from jobscout.pipeline.run import MyJobTab, list_my_jobs
from jobscout.pipeline.searches import get_search

router = APIRouter(prefix="/my-jobs", tags=["my jobs"])


@router.get("", response_model=MyJobsRead)
def read_my_jobs(
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
    tab: MyJobTab = "all",
    search_id: Annotated[int | None, Query(description="Only what this search found.")] = None,
) -> MyJobsRead:
    """Every job the user's searches found, once each, at its best score."""
    if search_id is not None:
        get_search(session, user_id, search_id)
    result = list_my_jobs(session, user_id, tab=tab, search_id=search_id)
    return MyJobsRead(
        items=[
            MyJobRead(
                match=read_match(item.match, item.job),
                searches=[SearchTitle(id=sid, title=title) for sid, title in item.searches],
            )
            for item in result.items
        ],
        counts=dict(result.counts),
    )

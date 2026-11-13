from datetime import timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from jobscout.api.deps import get_current_user_id, get_session
from jobscout.api.routers.matches import read_match
from jobscout.api.schemas import MyJobRead, MyJobsRead, SearchTitle
from jobscout.pipeline.run import MyJobSort, MyJobsQuery, MyJobTab, list_my_jobs
from jobscout.pipeline.searches import get_search

router = APIRouter(prefix="/my-jobs", tags=["my jobs"])

Since = Literal["24h", "7d", "30d"]
SINCE: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


@router.get("", response_model=MyJobsRead)
def read_my_jobs(
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
    tab: MyJobTab = "all",
    search_id: Annotated[int | None, Query(description="Only what this search found.")] = None,
    min_score: Annotated[int, Query(ge=0, le=100)] = 0,
    mode: Annotated[list[Literal["remote", "hybrid", "onsite"]], Query()] = [],  # noqa: B006
    source: Annotated[list[str], Query()] = [],  # noqa: B006
    since: Since | None = None,
    q: Annotated[str, Query(max_length=200, description="In the title or company.")] = "",
    sort: MyJobSort = "score",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> MyJobsRead:
    """Every job the user's searches found, once each, at its best score.

    The filters narrow the counts of every tab as well; `total` is the asked tab's.
    """
    if search_id is not None:
        get_search(session, user_id, search_id)
    query = MyJobsQuery(
        min_score=min_score,
        work_modes=frozenset(mode),
        sources=frozenset(source),
        since=SINCE[since] if since is not None else None,
        text=q,
        sort=sort,
    )
    result = list_my_jobs(
        session, user_id, tab=tab, search_id=search_id, limit=limit, query=query, offset=offset
    )
    return MyJobsRead(
        items=[
            MyJobRead(
                match=read_match(item.match, item.job),
                searches=[SearchTitle(id=sid, title=title) for sid, title in item.searches],
            )
            for item in result.items
        ],
        counts=dict(result.counts),
        total=result.total,
    )

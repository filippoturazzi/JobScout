from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from jobscout.api.deps import get_current_user_id, get_session
from jobscout.api.schemas import JobRead, MatchRead, MatchStatusUpdate
from jobscout.models import Job, Match
from jobscout.pipeline.run import list_matches, set_match_status

router = APIRouter(prefix="/matches", tags=["matches"])


def _read(match: Match, job: Job) -> MatchRead:
    assert match.id is not None
    return MatchRead(
        id=match.id,
        similarity=match.similarity,
        score=match.score,
        reasoning=match.reasoning,
        matched_skills=match.matched_skills,
        missing_skills=match.missing_skills,
        red_flags=match.red_flags,
        status=match.status,
        llm_model=match.llm_model,
        job=JobRead.model_validate(job),
    )


@router.get("", response_model=list[MatchRead])
def read_matches(
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
    min_score: Annotated[int, Query(ge=0, le=100)] = 0,
    status: Annotated[
        str | None,
        Query(
            description="Filter by match status; `low` reveals prefiltered, unscored rows, "
            "and `dismissed` or `applied` the ones the default listing hides."
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[MatchRead]:
    """Matches for the current user, best first. Inactive jobs are hidden.

    Unscored, dismissed and applied rows are hidden unless an explicit `status` is given.
    """
    rows = list_matches(session, user_id, min_score=min_score, status=status, limit=limit)
    return [_read(match, job) for match, job in rows]


@router.patch("/{match_id}", response_model=MatchRead)
def update_match(
    match_id: int,
    payload: MatchStatusUpdate,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> MatchRead:
    """Save, dismiss or mark applied. Dismissed and applied stick: no re-evaluation undoes them."""
    row = set_match_status(session, user_id, match_id, payload.status)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no match {match_id}")
    return _read(*row)

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from jobscout.api.deps import get_current_user_id, get_session
from jobscout.api.routers.jobs import read_job
from jobscout.api.schemas import MatchRead, MatchStatusUpdate
from jobscout.models import Job, Match
from jobscout.pipeline.run import set_match_status

router = APIRouter(prefix="/matches", tags=["matches"])


def read_match(match: Match, job: Job) -> MatchRead:
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
        job=read_job(job),
    )


@router.patch("/{match_id}", response_model=MatchRead)
def update_match(
    match_id: int,
    payload: MatchStatusUpdate,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> MatchRead:
    """Save, dismiss or mark applied; ``new`` takes the verdict back.

    Dismissed and applied stick: no re-evaluation undoes them, only the user.
    """
    row = set_match_status(session, user_id, match_id, payload.status)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no match {match_id}")
    return read_match(*row)

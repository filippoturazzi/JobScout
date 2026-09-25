from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from jobscout.api.deps import get_current_user_id, get_session
from jobscout.api.schemas import JobRead, MatchRead
from jobscout.pipeline.run import list_matches

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("", response_model=list[MatchRead])
def read_matches(
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
    min_score: Annotated[int, Query(ge=0, le=100)] = 0,
    status: Annotated[str | None, Query(description="Filter by match status.")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[MatchRead]:
    """Scored matches for the current user, best first. Inactive jobs are hidden."""
    rows = list_matches(session, user_id, min_score=min_score, status=status, limit=limit)
    result = []
    for match, job in rows:
        assert match.id is not None
        result.append(
            MatchRead(
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
        )
    return result

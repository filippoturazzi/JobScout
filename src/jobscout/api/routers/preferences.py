from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from jobscout.api.deps import get_current_user, get_session
from jobscout.api.schemas import PreferencesRead, PreferencesUpdate
from jobscout.models import User
from jobscout.pipeline.users import get_preferences, update_preferences

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=PreferencesRead)
def read_preferences(
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> PreferencesRead:
    return PreferencesRead.model_validate(get_preferences(session, user.id))


@router.put("", response_model=PreferencesRead)
def put_preferences(
    payload: PreferencesUpdate,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> PreferencesRead:
    changes = payload.model_dump(exclude_unset=True)
    try:
        prefs = update_preferences(session, user.id, changes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PreferencesRead.model_validate(prefs)

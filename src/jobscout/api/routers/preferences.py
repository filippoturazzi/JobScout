from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from jobscout.api.deps import get_current_user_id, get_session
from jobscout.api.schemas import PreferencesRead, PreferencesUpdate
from jobscout.config import get_settings
from jobscout.pipeline.run import save_preferences
from jobscout.pipeline.users import get_preferences

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=PreferencesRead)
def read_preferences(
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> PreferencesRead:
    return PreferencesRead.model_validate(get_preferences(session, user_id))


@router.put("", response_model=PreferencesRead)
def put_preferences(
    payload: PreferencesUpdate,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> PreferencesRead:
    changes = payload.model_dump(exclude_unset=True)
    settings = get_settings()
    try:
        prefs, _ = save_preferences(session, settings, user_id, changes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PreferencesRead.model_validate(prefs)

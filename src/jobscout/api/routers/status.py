from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from jobscout.api.deps import get_current_user, get_current_user_id, get_session
from jobscout.api.schemas import LocaleBody, StatusRead
from jobscout.config import get_settings
from jobscout.matching.llm import provider_key_found
from jobscout.models import User
from jobscout.pipeline.users import set_locale
from jobscout.scheduler import JobScoutScheduler
from jobscout.sources.registry import all_source_statuses

router = APIRouter(tags=["status"])


@router.get("/status", response_model=StatusRead)
def read_status(request: Request, user: Annotated[User, Depends(get_current_user)]) -> StatusRead:
    """What the page needs to know about the instance. Never the key itself."""
    settings = get_settings()
    scheduler: JobScoutScheduler | None = getattr(request.app.state, "scheduler", None)
    running = scheduler.running_search() if scheduler is not None else None
    return StatusRead(
        llm_key_found=provider_key_found(settings),
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        sources=all_source_statuses(settings),
        running_search_id=running[0] if running is not None else None,
        locale=user.locale,
    )


@router.put("/me/locale", response_model=LocaleBody)
def put_locale(
    payload: LocaleBody,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> LocaleBody:
    user = set_locale(session, user_id, payload.locale)
    return LocaleBody(locale=cast(Literal["en", "pt-BR"], user.locale))

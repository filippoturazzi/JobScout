from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from jobscout.api.deps import get_current_user, get_current_user_id, get_session
from jobscout.api.schemas import LocaleBody, StatusRead
from jobscout.config import get_settings
from jobscout.matching.llm import MissingProviderError, resolve_chat, resolve_embeddings
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
    # Searching needs both: the chat model reads and scores, the embeddings prefilter.
    key_found = True
    try:
        chat = resolve_chat(settings)
        llm_provider, llm_model = chat.provider, chat.model
    except MissingProviderError:
        key_found = False
        llm_provider, llm_model = settings.llm_provider or "", settings.llm_model or ""
    try:
        embed = resolve_embeddings(settings)
        embedding_provider, embedding_model = embed.provider, embed.model
    except MissingProviderError:
        key_found = False
        embedding_provider = settings.embedding_provider
        embedding_model = settings.embedding_model or ""
    return StatusRead(
        llm_key_found=key_found,
        llm_provider=llm_provider,
        llm_model=llm_model,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
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

"""FastAPI dependencies. JobScout is self-hosted and single-user: ``get_current_user`` returns
the one fixed user, and everything stays keyed by its id."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from langchain_core.language_models import BaseChatModel
from sqlmodel import Session

from jobscout.config import get_settings
from jobscout.db import get_engine
from jobscout.matching.llm import chat_model
from jobscout.models import User
from jobscout.pipeline.users import get_or_create_default_user


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def get_current_user(session: Annotated[Session, Depends(get_session)]) -> User:
    return get_or_create_default_user(session)


def get_current_user_id(user: Annotated[User, Depends(get_current_user)]) -> int:
    """The current user's id, non-optional."""
    assert user.id is not None, "a persisted user always has an id"
    return user.id


def get_chat_model() -> BaseChatModel:
    """The configured chat model. Raises ``MissingProviderError`` without a key."""
    return chat_model(get_settings())

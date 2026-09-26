"""FastAPI dependencies. ``get_current_user`` is the single seam auth will replace in stage 6."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session

from jobscout.db import get_engine
from jobscout.models import User
from jobscout.pipeline.users import get_or_create_default_user


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def get_current_user(session: Annotated[Session, Depends(get_session)]) -> User:
    return get_or_create_default_user(session)


def get_current_user_id(user: Annotated[User, Depends(get_current_user)]) -> int:
    """The current user's id, non-optional. Auth (stage 6) replaces get_current_user only."""
    assert user.id is not None, "a persisted user always has an id"
    return user.id

"""Builders shared across test modules."""

from typing import Any

from sqlmodel import Session

from jobscout.models import Search
from jobscout.pipeline.searches import add_search
from jobscout.pipeline.users import get_or_create_default_user, update_preferences


def make_search(
    session: Session, paragraph: str = "", title: str = "Test search", **prefs: Any
) -> Search:
    """A search for the default user, with `prefs` applied to its preferences."""
    user = get_or_create_default_user(session)
    assert user.id is not None
    search = add_search(session, user.id, title, paragraph)
    assert search.id is not None
    if prefs:
        update_preferences(session, search.id, prefs)
    return search

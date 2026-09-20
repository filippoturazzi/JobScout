"""Single fixed user until real auth arrives (stage 6). Everything is still keyed by user_id."""

from typing import Any

from sqlmodel import Session, select

from jobscout.models import User, UserPreferences

DEFAULT_USER_EMAIL = "me@localhost"

_PROTECTED_FIELDS = {"id", "user_id", "created_at", "updated_at", "profile_embedding"}


def get_or_create_default_user(session: Session) -> User:
    user = session.exec(select(User).where(User.email == DEFAULT_USER_EMAIL)).first()
    if user is None:
        user = User(email=DEFAULT_USER_EMAIL)
        session.add(user)
        session.commit()
        session.refresh(user)
    prefs = session.exec(select(UserPreferences).where(UserPreferences.user_id == user.id)).first()
    if prefs is None:
        session.add(UserPreferences(user_id=user.id))
        session.commit()
    return user


def get_preferences(session: Session, user_id: int) -> UserPreferences:
    prefs = session.exec(select(UserPreferences).where(UserPreferences.user_id == user_id)).first()
    if prefs is None:
        raise LookupError(f"No preferences for user_id={user_id}")
    return prefs


def update_preferences(session: Session, user_id: int, changes: dict[str, Any]) -> UserPreferences:
    allowed = set(UserPreferences.model_fields) - _PROTECTED_FIELDS
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"Unknown preference field(s): {', '.join(sorted(unknown))}")
    prefs = get_preferences(session, user_id)
    for field, value in changes.items():
        setattr(prefs, field, value)
    session.add(prefs)
    session.commit()
    session.refresh(prefs)
    return prefs

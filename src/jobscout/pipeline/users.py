"""Single fixed user until real auth arrives (stage 6). Everything is still keyed by user_id."""

from typing import Any

from sqlmodel import Session, select

from jobscout.models import User, UserPreferences
from jobscout.models.user import PROTECTED_PREFERENCE_FIELDS, non_nullable_preference_fields

DEFAULT_USER_EMAIL = "me@localhost"


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
    allowed = set(UserPreferences.model_fields) - PROTECTED_PREFERENCE_FIELDS
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"Unknown or protected preference field(s): {', '.join(sorted(unknown))}")
    non_nullable = non_nullable_preference_fields()
    non_nullable_nulls = sorted(
        field for field, value in changes.items() if value is None and field in non_nullable
    )
    if non_nullable_nulls:
        raise ValueError(f"Preference field(s) cannot be null: {', '.join(non_nullable_nulls)}")
    prefs = get_preferences(session, user_id)
    for field, value in changes.items():
        setattr(prefs, field, value)
    session.add(prefs)
    session.commit()
    session.refresh(prefs)
    return prefs

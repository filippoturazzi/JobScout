import pytest
from sqlmodel import select

from jobscout.models import User, UserPreferences
from jobscout.pipeline.users import (
    DEFAULT_USER_EMAIL,
    get_or_create_default_user,
    get_preferences,
    update_preferences,
)


def test_creates_user_and_empty_preferences_once(session):
    user = get_or_create_default_user(session)
    again = get_or_create_default_user(session)
    assert user.id == again.id
    assert user.email == DEFAULT_USER_EMAIL
    assert len(session.exec(select(User)).all()) == 1
    prefs = session.exec(select(UserPreferences)).one()
    assert prefs.user_id == user.id
    assert prefs.titles == []


def test_get_preferences(session):
    user = get_or_create_default_user(session)
    assert get_preferences(session, user.id).user_id == user.id


def test_get_preferences_missing_user_raises(session):
    with pytest.raises(LookupError):
        get_preferences(session, 999)


def test_update_preferences_partial(session):
    user = get_or_create_default_user(session)
    prefs = update_preferences(
        session, user.id, {"titles": ["AI Engineer"], "work_modes": ["remote"]}
    )
    assert prefs.titles == ["AI Engineer"]
    assert prefs.work_modes == ["remote"]
    prefs = update_preferences(session, user.id, {"min_salary": 60000})
    assert prefs.titles == ["AI Engineer"], "untouched fields are kept"
    assert prefs.min_salary == 60000


def test_update_preferences_rejects_unknown_field(session):
    user = get_or_create_default_user(session)
    with pytest.raises(ValueError, match="nope"):
        update_preferences(session, user.id, {"nope": 1})

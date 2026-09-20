from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from jobscout.models import Job, User, UserPreferences
from jobscout.models.base import utcnow


def test_utcnow_is_naive():
    now = utcnow()
    assert isinstance(now, datetime)
    assert now.tzinfo is None


def _job(**overrides) -> Job:
    data = dict(
        source="arbeitnow",
        external_id="abc-1",
        title="AI Engineer",
        company="Acme",
        location="Berlin",
        remote=True,
        url="https://example.com/abc-1",
        description="Build things.",
        tags=["python", "llm"],
        content_hash="h1",
        raw={"slug": "abc-1"},
    )
    data.update(overrides)
    return Job(**data)


def test_job_roundtrip_with_json_columns(session):
    session.add(_job())
    session.commit()
    job = session.exec(select(Job)).one()
    assert job.tags == ["python", "llm"]
    assert job.raw == {"slug": "abc-1"}
    assert job.is_active is True
    assert job.first_seen_at.tzinfo is None
    assert job.embedding is None


def test_job_source_external_id_is_unique(session):
    session.add(_job())
    session.commit()
    session.add(_job(title="Duplicate"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_user_preferences_one_to_one(session):
    user = User(email="me@localhost")
    session.add(user)
    session.commit()
    session.add(UserPreferences(user_id=user.id, titles=["AI Engineer"]))
    session.commit()
    prefs = session.exec(select(UserPreferences)).one()
    assert prefs.titles == ["AI Engineer"]
    assert prefs.min_score_to_notify == 70
    assert prefs.work_modes == []
    session.add(UserPreferences(user_id=user.id))
    with pytest.raises(IntegrityError):
        session.commit()

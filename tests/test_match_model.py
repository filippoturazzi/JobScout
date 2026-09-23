import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from jobscout.models import Job, Match, User


def _job(session, external_id="j1") -> Job:
    job = Job(
        source="t",
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        url=f"https://x/{external_id}",
        description="d",
        content_hash="h",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _user(session) -> User:
    user = User(email="a@b")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_match_roundtrip_defaults(session):
    job, user = _job(session), _user(session)
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.42))
    session.commit()
    match = session.exec(select(Match)).one()
    assert match.score is None and match.reasoning is None
    assert match.matched_skills == [] and match.missing_skills == [] and match.red_flags == []
    assert match.status == "new"
    assert match.llm_model is None
    assert match.created_at.tzinfo is None


def test_match_is_unique_per_job_and_user(session):
    job, user = _job(session), _user(session)
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.1))
    session.commit()
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.2))
    with pytest.raises(IntegrityError):
        session.commit()


def test_status_sets_are_consistent():
    from jobscout.models.match import MATCH_STATUSES, REEVALUATABLE_STATUSES

    assert (
        frozenset({"new", "seen", "saved", "dismissed", "notified", "low", "stale"})
        == MATCH_STATUSES
    )
    assert frozenset({"stale"}) == REEVALUATABLE_STATUSES
    assert "dismissed" not in REEVALUATABLE_STATUSES

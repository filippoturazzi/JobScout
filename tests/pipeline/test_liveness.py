from datetime import timedelta

from sqlmodel import Session

from jobscout.config import Settings
from jobscout.models import Job
from jobscout.models.base import utcnow
from jobscout.pipeline.liveness import deactivate_stale_jobs


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _add_job(session: Session, source: str, external_id: str, days_ago: int) -> Job:
    seen = utcnow() - timedelta(days=days_ago)
    job = Job(
        source=source,
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        remote=True,
        url=f"https://x/{external_id}",
        description="Python LLM work.",
        content_hash=f"h-{external_id}",
        first_seen_at=seen,
        last_seen_at=seen,
        is_active=True,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_deactivates_only_jobs_older_than_the_window(session: Session):
    old = _add_job(session, "arbeitnow", "old", days_ago=20)
    fresh = _add_job(session, "arbeitnow", "fresh", days_ago=3)

    flipped = deactivate_stale_jobs(session, _settings(inactive_after_days=14), "arbeitnow")
    session.commit()

    assert flipped == 1
    assert session.get(Job, old.id).is_active is False
    assert session.get(Job, fresh.id).is_active is True


def test_leaves_other_sources_alone(session: Session):
    """The caller only passes sources that answered; a source that errored must keep
    its catalogue. 'I did not ask' is not 'it no longer exists'."""
    mine = _add_job(session, "arbeitnow", "mine", days_ago=20)
    theirs = _add_job(session, "remotive", "theirs", days_ago=20)

    flipped = deactivate_stale_jobs(session, _settings(inactive_after_days=14), "arbeitnow")
    session.commit()

    assert flipped == 1
    assert session.get(Job, mine.id).is_active is False
    assert session.get(Job, theirs.id).is_active is True


def test_already_inactive_jobs_are_not_counted_again(session: Session):
    job = _add_job(session, "arbeitnow", "old", days_ago=20)
    job.is_active = False
    session.add(job)
    session.commit()

    flipped = deactivate_stale_jobs(session, _settings(inactive_after_days=14), "arbeitnow")
    session.commit()

    assert flipped == 0


def test_does_not_commit_on_its_own(session: Session):
    """The caller owns the transaction: the ingest job batches this with its Run row."""
    job = _add_job(session, "arbeitnow", "old", days_ago=20)

    deactivate_stale_jobs(session, _settings(inactive_after_days=14), "arbeitnow")
    session.rollback()

    assert session.get(Job, job.id).is_active is True

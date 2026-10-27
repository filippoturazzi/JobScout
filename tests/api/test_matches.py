import pytest
from sqlmodel import select

from jobscout.models import Job, Match, User
from jobscout.pipeline.ingest import upsert_jobs
from jobscout.sources.base import RawJob


def _job(session, external_id="a", active=True) -> Job:
    job = Job(
        source="t",
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        remote=True,
        url=f"https://x/{external_id}",
        description="d",
        content_hash=f"h-{external_id}",
        is_active=active,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _bootstrap_user(client, session) -> User:
    client.get("/preferences")  # creates the default user
    return session.exec(select(User)).one()


def test_matches_empty(client):
    assert client.get("/matches").json() == []


def test_matches_returns_scored_rows_newest_score_first(client, session):
    user = _bootstrap_user(client, session)
    low = _job(session, "low")
    high = _job(session, "high")
    session.add(Match(job_id=low.id, user_id=user.id, similarity=0.5, score=40, status="new"))
    session.add(
        Match(
            job_id=high.id,
            user_id=user.id,
            similarity=0.8,
            score=90,
            reasoning="Strong.",
            matched_skills=["Python"],
            status="new",
        )
    )
    session.commit()

    body = client.get("/matches").json()

    assert [m["score"] for m in body] == [90, 40]
    assert body[0]["job"]["external_id"] == "high"
    assert body[0]["matched_skills"] == ["Python"]
    assert "raw" not in body[0]["job"] and "embedding" not in body[0]["job"]


def test_matches_hides_inactive_jobs(client, session):
    user = _bootstrap_user(client, session)
    job = _job(session, "gone", active=False)
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, score=95, status="new"))
    session.commit()

    assert client.get("/matches").json() == []


def test_matches_filters_by_min_score_and_status(client, session):
    user = _bootstrap_user(client, session)
    a = _job(session, "a")
    b = _job(session, "b")
    session.add(Match(job_id=a.id, user_id=user.id, similarity=0.5, score=40, status="new"))
    session.add(Match(job_id=b.id, user_id=user.id, similarity=0.9, score=95, status="saved"))
    session.commit()

    assert [m["score"] for m in client.get("/matches", params={"min_score": 50}).json()] == [95]
    assert [
        m["job"]["external_id"] for m in client.get("/matches", params={"status": "saved"}).json()
    ] == ["b"]


def test_unscored_low_rows_are_hidden_by_default_but_returned_for_status_low(client, session):
    """`?status=low` answers "why didn't this job show up"; the default listing stays clean."""
    user = _bootstrap_user(client, session)
    scored = _job(session, "scored")
    low = _job(session, "low")
    session.add(Match(job_id=scored.id, user_id=user.id, similarity=0.7, score=80, status="new"))
    session.add(Match(job_id=low.id, user_id=user.id, similarity=0.1, score=None, status="low"))
    session.commit()

    default = client.get("/matches").json()
    assert [m["job"]["external_id"] for m in default] == ["scored"]

    explicit = client.get("/matches", params={"status": "low"}).json()
    assert [m["job"]["external_id"] for m in explicit] == ["low"]
    assert explicit[0]["score"] is None


def _match(session, user, status="new", external_id="m") -> Match:
    job = _job(session, external_id)
    match = Match(job_id=job.id, user_id=user.id, similarity=0.7, score=70, status=status)
    session.add(match)
    session.commit()
    session.refresh(match)
    return match


@pytest.mark.parametrize("status", ["saved", "dismissed", "applied"])
def test_patch_sets_a_user_status(client, session, status):
    user = _bootstrap_user(client, session)
    match = _match(session, user)
    response = client.patch(f"/matches/{match.id}", json={"status": status})
    assert response.status_code == 200
    assert response.json()["status"] == status
    session.refresh(match)
    assert match.status == status


@pytest.mark.parametrize("status", ["stale", "low", "new", "bogus"])
def test_patch_rejects_a_status_the_user_cannot_set(client, session, status):
    user = _bootstrap_user(client, session)
    match = _match(session, user)
    assert client.patch(f"/matches/{match.id}", json={"status": status}).status_code == 422
    session.refresh(match)
    assert match.status == "new"


def test_patch_an_unknown_or_another_users_match_is_404(client, session):
    _bootstrap_user(client, session)
    other = User(email="other@example.com")
    session.add(other)
    session.commit()
    theirs = _match(session, other)
    assert client.patch(f"/matches/{theirs.id}", json={"status": "saved"}).status_code == 404
    assert client.patch("/matches/9999", json={"status": "saved"}).status_code == 404
    session.refresh(theirs)
    assert theirs.status == "new"


def test_staling_does_not_revive_an_applied_match(client, session):
    user = _bootstrap_user(client, session)
    applied = _match(session, user, status="applied", external_id="a")
    saved = _match(session, user, status="saved", external_id="s")
    # A matching-relevant preference change stales every match the user has not closed.
    client.put("/preferences", json={"titles": ["Data Engineer"]})
    session.refresh(applied)
    session.refresh(saved)
    assert applied.status == "applied"
    assert saved.status == "stale"


def test_a_changed_job_does_not_revive_an_applied_match(client, session):
    user = _bootstrap_user(client, session)
    match = _match(session, user, status="applied", external_id="c")
    changed = RawJob(
        source="t",
        external_id="c",
        title="AI Engineer",
        company="Acme",
        url="https://x/c",
        description="a new description",
    )
    upsert_jobs(session, [changed])
    session.refresh(match)
    assert match.status == "applied"


def test_dismissed_and_applied_are_hidden_from_the_default_listing(client, session):
    user = _bootstrap_user(client, session)
    for status in ("new", "saved", "dismissed", "applied"):
        _match(session, user, status=status, external_id=status)
    listed = {m["job"]["external_id"] for m in client.get("/matches").json()}
    assert listed == {"new", "saved"}


@pytest.mark.parametrize("status", ["dismissed", "applied"])
def test_they_are_returned_when_asked_for_by_status(client, session, status):
    user = _bootstrap_user(client, session)
    _match(session, user, status=status, external_id="x")
    body = client.get("/matches", params={"status": status}).json()
    assert [m["status"] for m in body] == [status]

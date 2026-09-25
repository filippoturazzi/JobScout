from sqlmodel import select

from jobscout.models import Job, Match, User


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


def test_matches_excludes_unscored_low_rows(client, session):
    user = _bootstrap_user(client, session)
    job = _job(session, "a")
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.1, score=None, status="low"))
    session.commit()

    assert client.get("/matches").json() == []

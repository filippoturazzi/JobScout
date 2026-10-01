from sqlmodel import select

from jobscout.models import Job, Match, User
from jobscout.models.user import non_nullable_preference_fields


def test_get_preferences_bootstraps_default_user(client):
    r = client.get("/preferences")
    assert r.status_code == 200
    body = r.json()
    assert body["titles"] == []
    assert body["min_score_to_notify"] == 70
    assert "profile_embedding" not in body


def test_put_preferences_partial_update(client):
    r = client.put("/preferences", json={"titles": ["AI Engineer"], "work_modes": ["remote"]})
    assert r.status_code == 200
    assert r.json()["titles"] == ["AI Engineer"]

    r = client.put("/preferences", json={"min_salary": 60000})
    assert r.status_code == 200
    assert r.json()["titles"] == ["AI Engineer"]
    assert r.json()["min_salary"] == 60000


def test_put_preferences_validates_work_mode(client):
    r = client.put("/preferences", json={"work_modes": ["on-the-moon"]})
    assert r.status_code == 422


def test_put_preferences_rejects_unknown_field(client):
    r = client.put("/preferences", json={"favorite_color": "blue"})
    assert r.status_code == 422


def test_put_preferences_rejects_explicit_null_on_non_nullable_field(client):
    r = client.put("/preferences", json={"titles": None})
    assert r.status_code == 422

    r = client.get("/preferences")
    assert r.status_code == 200
    assert r.json()["titles"] == []


def test_put_preferences_allows_explicit_null_on_nullable_field(client):
    r = client.put("/preferences", json={"min_salary": 60000})
    assert r.status_code == 200
    assert r.json()["min_salary"] == 60000

    r = client.put("/preferences", json={"min_salary": None})
    assert r.status_code == 200
    assert r.json()["min_salary"] is None


def test_update_schema_rejects_null_for_every_non_nullable_field(client):
    for name in sorted(non_nullable_preference_fields()):
        r = client.put("/preferences", json={name: None})
        assert r.status_code == 422, name


def test_put_preferences_marks_stale_matches_on_matching_relevant_change(client, session):
    client.get("/preferences")  # creates the default user
    user = session.exec(select(User)).one()
    job = Job(
        source="t",
        external_id="a",
        title="AI Engineer",
        company="Acme",
        remote=True,
        url="https://x/a",
        description="d",
        content_hash="h-a",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    match = Match(job_id=job.id, user_id=user.id, similarity=0.5, score=40, status="new")
    session.add(match)
    session.commit()

    r = client.put("/preferences", json={"titles": ["AI Engineer"]})
    assert r.status_code == 200

    session.refresh(match)
    assert match.status == "stale"


def test_put_preferences_wakes_matching_without_scoring_inline(client, monkeypatch):
    import jobscout.api.routers.preferences as preferences_router

    woken = []
    monkeypatch.setattr(
        preferences_router, "wake_matching", lambda scheduler: woken.append(scheduler)
    )

    response = client.put("/preferences", json={"profile_summary": "Python LLM engineer."})

    assert response.status_code == 200
    assert response.json()["profile_summary"] == "Python LLM engineer."
    assert len(woken) == 1


def test_put_preferences_survives_a_failing_wake(client, monkeypatch):
    """The save is committed before the wake: a broken scheduler must not report a 500."""
    import jobscout.api.routers.preferences as preferences_router

    def _boom(_scheduler):
        raise RuntimeError("scheduler is down")

    monkeypatch.setattr(preferences_router, "wake_matching", _boom)

    response = client.put("/preferences", json={"profile_summary": "Python LLM engineer."})

    assert response.status_code == 200
    assert client.get("/preferences").json()["profile_summary"] == "Python LLM engineer."

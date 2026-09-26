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

    # profile_summary stays empty, so the resulting backfill has nothing to evaluate
    # and never needs an LLM/embeddings provider — see pipeline.matching.run_match.
    r = client.put("/preferences", json={"titles": ["AI Engineer"]})
    assert r.status_code == 200

    session.refresh(match)
    assert match.status == "stale"


def test_put_preferences_succeeds_without_a_configured_provider(client, session, monkeypatch):
    import jobscout.pipeline.matching as matching_module
    from jobscout.matching.llm import MissingProviderError

    # A job must exist and pass the preference filter so the backfill actually reaches
    # `select_candidates` -> `embeddings(settings)`; otherwise the provider is never touched
    # and this test would pass even without the fix.
    client.get("/preferences")  # creates the default user
    session.add(
        Job(
            source="t",
            external_id="a",
            title="AI Engineer",
            company="Acme",
            remote=True,
            url="https://x/a",
            description="d",
            content_hash="h-a",
        )
    )
    session.commit()

    def _no_provider(_settings):
        raise MissingProviderError("GOOGLE_API_KEY is not set.")

    monkeypatch.setattr(matching_module, "embeddings", _no_provider)
    client.put("/preferences", json={"profile_summary": "Python LLM engineer."})

    response = client.put("/preferences", json={"titles": ["AI Engineer"]})

    assert response.status_code == 200
    assert response.json()["titles"] == ["AI Engineer"]


def test_put_preferences_survives_a_provider_runtime_error(client, session, monkeypatch):
    """The preferences commit happens before the backfill; a 429 must not report a 500."""
    import jobscout.pipeline.matching as matching_module

    client.get("/preferences")  # creates the default user
    session.add(
        Job(
            source="t",
            external_id="a",
            title="AI Engineer",
            company="Acme",
            remote=True,
            url="https://x/a",
            description="d",
            content_hash="h-a",
        )
    )
    session.commit()

    def _rate_limited(_settings):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(matching_module, "embeddings", _rate_limited)

    response = client.put("/preferences", json={"profile_summary": "Python LLM engineer."})

    assert response.status_code == 200
    assert response.json()["profile_summary"] == "Python LLM engineer."

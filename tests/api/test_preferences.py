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

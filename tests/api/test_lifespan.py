from fastapi.testclient import TestClient

import jobscout.db as db
from jobscout.api.app import app
from jobscout.config import Settings


def test_lifespan_initializes_db_and_default_user(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setattr(db, "get_settings", lambda: settings)
    assert not app.dependency_overrides, "this test must exercise the real dependency path"

    with TestClient(app) as client:
        response = client.get("/preferences")

    assert response.status_code == 200
    assert response.json()["titles"] == []

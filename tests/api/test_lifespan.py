from fastapi.testclient import TestClient

import jobscout.api.app as app_module
import jobscout.db as db
from jobscout.api.app import app
from jobscout.config import Settings


def _point_settings_at(tmp_path, monkeypatch, *, scheduler_enabled: bool) -> Settings:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'api.db'}",
        scheduler_enabled=scheduler_enabled,
    )
    monkeypatch.setattr(db, "get_settings", lambda: settings)
    monkeypatch.setattr(app_module, "get_settings", lambda: settings)
    return settings


def test_lifespan_initializes_db_and_default_user(tmp_path, monkeypatch):
    _point_settings_at(tmp_path, monkeypatch, scheduler_enabled=False)
    assert not app.dependency_overrides, "this test must exercise the real dependency path"

    with TestClient(app) as client:
        response = client.get("/preferences")

    assert response.status_code == 200
    assert response.json()["titles"] == []


def test_lifespan_starts_and_stops_the_scheduler(tmp_path, monkeypatch):
    _point_settings_at(tmp_path, monkeypatch, scheduler_enabled=True)

    with TestClient(app) as client:
        scheduler = client.app.state.scheduler
        assert {job.id for job in scheduler.get_jobs()} == {"ingest", "match"}

    assert scheduler.get_jobs() == [], "shutdown must leave no jobs armed"


def test_lifespan_honours_the_disable_flag(tmp_path, monkeypatch):
    """Without this, every test that builds the app would start background threads."""
    _point_settings_at(tmp_path, monkeypatch, scheduler_enabled=False)

    with TestClient(app) as client:
        assert client.app.state.scheduler.get_jobs() == []

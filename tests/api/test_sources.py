from jobscout.config import Settings
from jobscout.sources import registry


def test_get_sources_names_active_and_dormant_ones(client, monkeypatch):
    settings = Settings(_env_file=None, sources="himalayas,remotive")
    monkeypatch.setattr("jobscout.api.routers.sources.get_settings", lambda: settings)
    # No shipped source needs a key today, so register one that does.
    monkeypatch.setitem(registry.SOURCE_MISSING_CREDENTIALS, "remotive", lambda s: ["FAKE_KEY"])
    assert client.get("/sources").json() == [
        {"name": "himalayas", "active": True, "reason": None},
        {"name": "remotive", "active": False, "reason": "missing FAKE_KEY"},
    ]

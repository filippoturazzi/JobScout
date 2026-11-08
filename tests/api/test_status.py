from sqlmodel import select

from jobscout.models import User


def test_status_reports_the_key_without_revealing_it(client, monkeypatch, fake_scheduler):
    monkeypatch.setenv("LLM_PROVIDER", "google")
    monkeypatch.setenv("GOOGLE_API_KEY", "super-secret-value")
    response = client.get("/status")
    assert response.status_code == 200
    body = response.json()
    assert body["llm_key_found"] is True
    assert body["llm_provider"] == "google"
    assert body["running_search_id"] is None
    assert body["locale"] == "en"
    assert "himalayas" in {s["name"] for s in body["sources"]}
    assert "super-secret-value" not in response.text
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    from jobscout.config import get_settings

    get_settings.cache_clear()
    assert client.get("/status").json()["llm_key_found"] is False
    fake_scheduler.running = (4, 9)
    assert client.get("/status").json()["running_search_id"] == 4


def test_locale_is_saved(client, session):
    assert client.put("/me/locale", json={"locale": "pt-BR"}).json() == {"locale": "pt-BR"}
    assert client.get("/status").json()["locale"] == "pt-BR"
    assert client.put("/me/locale", json={"locale": "fr"}).status_code == 422
    assert session.exec(select(User)).one().locale == "pt-BR"


def test_status_lists_off_sources_after_the_configured_ones(client, monkeypatch, fake_scheduler):
    from jobscout.config import get_settings

    monkeypatch.setenv("SOURCES", "himalayas")
    get_settings.cache_clear()
    sources = client.get("/status").json()["sources"]
    assert sources[0] == {"name": "himalayas", "active": True, "reason": None}
    rest = sources[1:]
    assert {s["name"] for s in rest} == {"arbeitnow", "remotive", "linkedin", "indeed"}
    assert all(s["active"] is False and s["reason"] == "off" for s in rest)

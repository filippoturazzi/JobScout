from datetime import datetime

from jobscout.pipeline.ingest import upsert_jobs
from jobscout.sources.base import RawJob

T0 = datetime(2026, 9, 20, 12, 0, 0)


def raw(external_id, title, remote=True) -> RawJob:
    return RawJob(
        source="fake",
        external_id=external_id,
        title=title,
        company="Acme",
        location="Berlin",
        remote=remote,
        url=f"https://x/{external_id}",
        description="d",
        tags=["python"],
    )


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_jobs_empty(client):
    r = client.get("/jobs")
    assert r.status_code == 200
    assert r.json() == []


def test_list_jobs_applies_preferences(client, session):
    upsert_jobs(session, [raw("a", "AI Engineer"), raw("b", "Data Analyst")], now=T0)
    client.put("/preferences", json={"titles": ["AI Engineer"]})

    r = client.get("/jobs")
    assert [j["external_id"] for j in r.json()] == ["a"]
    body = r.json()[0]
    assert body["title"] == "AI Engineer"
    assert body["tags"] == ["python"]
    assert "raw" not in body
    assert "embedding" not in body

    r = client.get("/jobs", params={"all": "true"})
    assert {j["external_id"] for j in r.json()} == {"a", "b"}

    r = client.get("/jobs", params={"limit": 1, "all": "true"})
    assert len(r.json()) == 1

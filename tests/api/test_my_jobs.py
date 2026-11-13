from jobscout.models import Job, Match
from jobscout.pipeline.users import get_or_create_default_user
from tests.helpers import make_search


def _job(session, external_id="a") -> Job:
    job = Job(
        source="t",
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        remote=True,
        url=f"https://x/{external_id}",
        description="d",
        content_hash=f"h-{external_id}",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_my_jobs_lists_across_searches(client, session):
    user = get_or_create_default_user(session)
    a, b = make_search(session, title="A"), make_search(session, title="B")
    job = _job(session)
    for search, score in ((a, 60), (b, 90)):
        session.add(
            Match(
                job_id=job.id,
                user_id=user.id,
                search_id=search.id,
                similarity=0.5,
                score=score,
                status="new",
            )
        )
    session.commit()
    body = client.get("/my-jobs").json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["match"]["score"] == 90
    assert {s["title"] for s in item["searches"]} == {"A", "B"}
    assert body["counts"] == {"all": 1, "saved": 0, "applied": 0, "dismissed": 0}
    only_a = client.get("/my-jobs", params={"search_id": a.id}).json()
    assert only_a["items"][0]["match"]["score"] == 60
    assert client.get("/my-jobs", params={"tab": "bogus"}).status_code == 422


def test_my_jobs_takes_filters_sort_and_a_page(client, session):
    user = get_or_create_default_user(session)
    search = make_search(session, title="A")
    for n, (score, source) in enumerate(((90, "indeed"), (70, "linkedin"), (40, "indeed"))):
        job = _job(session, str(n))
        job.source = source
        session.add(job)
        session.add(
            Match(job_id=job.id, user_id=user.id, search_id=search.id, similarity=0.5, score=score)
        )
    session.commit()
    params = {"min_score": 50, "source": ["indeed", "linkedin"], "mode": "remote", "since": "30d"}
    body = client.get("/my-jobs", params=params).json()
    assert [i["match"]["score"] for i in body["items"]] == [90, 70]
    assert body["total"] == 2
    page = client.get("/my-jobs", params={"limit": 1, "offset": 1, "sort": "company"}).json()
    assert len(page["items"]) == 1 and page["total"] == 3
    assert client.get("/my-jobs", params={"tab": "dismissed"}).json()["items"] == []
    assert client.get("/my-jobs", params={"since": "1y"}).status_code == 422
    assert client.get("/my-jobs", params={"mode": "space"}).status_code == 422

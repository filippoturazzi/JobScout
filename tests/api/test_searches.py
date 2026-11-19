from datetime import datetime

import pytest

from jobscout.api.app import app
from jobscout.models import Job, Match, Run, Search, User
from jobscout.pipeline.ingest import upsert_jobs
from jobscout.pipeline.users import get_or_create_default_user, get_preferences
from jobscout.sources.base import RawJob
from tests.api.conftest import reading
from tests.helpers import fetched, make_search

PARAGRAPH = "Junior AI engineer, remote from Portugal, Python and LangChain."


def _create(client, paragraph=PARAGRAPH):
    return client.post("/searches", json={"paragraph": paragraph})


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


def test_create_search_returns_the_first_question(client, chat):
    chat.results = [reading(seniority=[])]
    response = _create(client)
    assert response.status_code == 201
    body = response.json()
    assert body["question"]["id"] == "level"
    assert body["question"]["position"] == 1
    assert body["paragraph"] == PARAGRAPH
    assert body["reading"]["terms"] == ["ai engineer"]
    assert body["confirmed"] is False
    assert body["latest_run"] is None
    assert client.get(f"/searches/{body['id']}").json() == body


def test_create_search_without_a_key_is_refused(client, chat, monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    response = _create(client)
    assert response.status_code == 409
    assert response.json()["code"] == "no_llm_key"
    assert client.get("/searches").json() == []
    assert chat.calls == 0


def test_a_blank_paragraph_is_422(client, chat):
    assert _create(client, "   ").status_code == 422


def test_list_searches_names_the_running_one(client, chat, fake_scheduler):
    first = _create(client).json()["id"]
    second = _create(client).json()["id"]
    fake_scheduler.running = (first, 1)
    listed = client.get("/searches").json()
    assert {item["id"]: item["running"] for item in listed} == {first: True, second: False}
    assert set(listed[0]) == {"id", "title", "last_used_at", "running", "match_count"}


def test_answering_moves_to_the_next_question(client, chat):
    chat.results = [reading(seniority=[], stated_work_modes=[])]
    created = _create(client).json()
    assert created["question"]["id"] == "level"
    response = client.post(
        f"/searches/{created['id']}/answers", json={"question": "level", "choice": "junior"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["question"]["id"] == "work_modes"
    assert body["answers"]["level"] == {"choice": "junior", "values": []}
    assert body["asked"] == ["level"]


def test_an_invalid_answer_is_422(client, chat):
    chat.results = [reading(seniority=[])]
    created = _create(client).json()
    response = client.post(
        f"/searches/{created['id']}/answers", json={"question": "level", "choice": "wizard"}
    )
    assert response.status_code == 422


def test_refining_returns_the_summary_without_running(client, chat, fake_scheduler):
    created = _create(client).json()
    chat.results = [reading(terms=["ml engineer"])]
    chat.calls = 0
    response = client.post(f"/searches/{created['id']}/refinements", json={"text": "or ML"})
    assert response.status_code == 200
    body = response.json()
    assert body["refinements"] == ["or ML"]
    assert body["summary"]["role"] == "ml engineer"
    assert client.get("/runs").json() == []
    assert fake_scheduler.started == []


def test_reread_retries_a_failed_reading(client, chat):
    chat.error = RuntimeError("quota")
    created = _create(client).json()
    assert created["reading"] is None
    assert created["reading_error"] == "RuntimeError: quota"
    chat.error = None
    body = client.post(f"/searches/{created['id']}/reread").json()
    assert body["reading_error"] is None
    assert body["reading"]["terms"] == ["ai engineer"]


def test_widenings_are_listed(client, chat):
    body = _create(client).json()
    assert {"id", "question", "answer"} == set(body["widenings"][0])
    assert "any_level" in {w["id"] for w in body["widenings"]}


def test_run_refuses_with_questions_pending(client, chat, fake_scheduler):
    chat.results = [reading(seniority=[])]
    created = _create(client).json()
    response = client.post(f"/searches/{created['id']}/run")
    assert response.status_code == 409
    assert response.json()["code"] == "questions_pending"
    assert fake_scheduler.started == []


def test_run_starts_and_reports_progress(client, chat, fake_scheduler):
    created = _create(client).json()
    response = client.post(f"/searches/{created['id']}/run")
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert fake_scheduler.started == [(created["id"], True)]
    reread = client.get(f"/searches/{created['id']}").json()
    assert reread["confirmed"] is True
    assert reread["latest_run"]["id"] == run_id
    run = client.get(f"/searches/{created['id']}/runs/{run_id}")
    assert run.status_code == 200
    assert run.json()["search_id"] == created["id"]


def test_a_run_of_another_search_is_404(client, chat, fake_scheduler):
    first = _create(client).json()["id"]
    second = _create(client).json()["id"]
    run_id = client.post(f"/searches/{first}/run").json()["run_id"]
    assert client.get(f"/searches/{second}/runs/{run_id}").status_code == 404


def test_rank_starts_without_fetching(client, chat, fake_scheduler):
    created = _create(client).json()
    response = client.post(f"/searches/{created['id']}/rank")
    assert response.status_code == 202
    assert fake_scheduler.started == [(created["id"], False)]


def test_starting_a_second_search_is_409_and_changes_nothing(client, chat, fake_scheduler):
    first = _create(client).json()["id"]
    second = _create(client).json()["id"]
    fake_scheduler.running = (first, 7)
    for path in ("run", "rank"):
        response = client.post(f"/searches/{second}/{path}")
        assert response.status_code == 409
        assert response.json() == {
            "detail": "Another search is running",
            "code": "search_busy",
            "search_id": first,
        }
    assert fake_scheduler.started == []
    assert client.get(f"/searches/{second}").json()["confirmed"] is False


@pytest.mark.parametrize("path", ["run", "rank"])
def test_starting_the_running_search_again_returns_its_run_and_changes_nothing(
    client, session, chat, fake_scheduler, path
):
    created = _create(client).json()
    search_id = created["id"]
    in_flight = client.post(f"/searches/{search_id}/run").json()["run_id"]
    job = _job(session)
    match = Match(
        job_id=job.id, user_id=1, search_id=search_id, similarity=0.7, score=80, status="new"
    )
    session.add(match)
    session.commit()
    chat.results = [reading(terms=["ml engineer"])]
    client.post(f"/searches/{search_id}/refinements", json={"text": "or ML"})
    fake_scheduler.running = (search_id, in_flight)

    response = client.post(f"/searches/{search_id}/{path}")

    assert response.status_code == 202
    assert response.json() == {"run_id": in_flight}
    assert fake_scheduler.started == [(search_id, True)], "nothing new was started"
    session.expire_all()
    assert get_preferences(session, search_id).search_terms == ["ai engineer"]
    assert session.get(Match, match.id).status == "new", "the run in flight keeps its matches"
    assert client.get(f"/searches/{search_id}").json()["confirmed"] is False


def test_run_without_a_scheduler_is_503(client, chat, monkeypatch):
    monkeypatch.delattr(app.state, "scheduler", raising=False)
    created = _create(client).json()
    assert client.post(f"/searches/{created['id']}/run").status_code == 503
    assert client.post(f"/searches/{created['id']}/rank").status_code == 503


def test_deleting_a_search_removes_it(client, chat, fake_scheduler):
    created = _create(client).json()
    assert client.delete(f"/searches/{created['id']}").status_code == 204
    assert client.get(f"/searches/{created['id']}").status_code == 404


def test_deleting_the_running_search_is_refused(client, chat, fake_scheduler):
    created = _create(client).json()
    fake_scheduler.running = (created["id"], 3)
    response = client.delete(f"/searches/{created['id']}")
    assert response.status_code == 409
    assert response.json()["code"] == "search_busy"
    assert client.get(f"/searches/{created['id']}").status_code == 200


def test_latest_run_is_the_newest_of_this_search(client, session, chat):
    created = _create(client).json()
    other = _create(client).json()
    session.add(Run(job="search", search_id=created["id"], counters={"n": 1}))
    session.add(Run(job="search", search_id=created["id"], counters={"n": 2}))
    session.add(Run(job="search", search_id=other["id"], counters={"n": 3}))
    session.commit()
    latest = client.get(f"/searches/{created['id']}").json()["latest_run"]
    assert latest["counters"] == {"n": 2}


def test_matches_report_found_and_waiting(client, session):
    user = get_or_create_default_user(session)
    search = make_search(session)
    scored, waiting = _job(session, "scored"), _job(session, "waiting")
    fetched(session, search, scored, waiting)
    session.add(
        Match(
            job_id=scored.id,
            user_id=user.id,
            search_id=search.id,
            similarity=0.7,
            score=80,
            status="new",
        )
    )
    session.commit()
    body = client.get(f"/searches/{search.id}/matches").json()
    assert [m["score"] for m in body["matches"]] == [80]
    assert body["found"] == 1
    assert body["waiting"] == 1


def test_matches_include_unscored_jobs(client, session):
    user = get_or_create_default_user(session)
    search = make_search(session)
    scored, waiting, low = _job(session, "scored"), _job(session, "waiting"), _job(session, "low")
    fetched(session, search, scored, waiting, low)
    for job, score, status, similarity in ((scored, 80, "new", 0.7), (low, None, "low", 0.2)):
        session.add(
            Match(
                job_id=job.id,
                user_id=user.id,
                search_id=search.id,
                similarity=similarity,
                score=score,
                status=status,
            )
        )
    session.commit()
    body = client.get(f"/searches/{search.id}/matches").json()
    assert body["found"] == 1
    assert body["waiting"] == 1
    by_id = {item["job"]["id"]: item for item in body["unscored"]}
    assert set(by_id) == {waiting.id, low.id}
    assert by_id[low.id]["similarity"] == pytest.approx(0.2)
    assert by_id[low.id]["match_id"] is not None
    assert by_id[waiting.id]["match_id"] is None
    assert by_id[waiting.id]["similarity"] is None


def test_matches_leave_unscored_out_when_asked(client, session):
    search = make_search(session)
    waiting = _job(session, "waiting")
    fetched(session, search, waiting)
    body = client.get(f"/searches/{search.id}/matches?unscored=false").json()
    assert body["unscored"] == []
    assert body["waiting"] == 1


def test_matches_unscored_is_empty_when_everything_is_scored(client, session):
    user = get_or_create_default_user(session)
    search = make_search(session)
    scored = _job(session, "scored")
    fetched(session, search, scored)
    session.add(
        Match(
            job_id=scored.id,
            user_id=user.id,
            search_id=search.id,
            similarity=0.7,
            score=80,
            status="new",
        )
    )
    session.commit()
    body = client.get(f"/searches/{search.id}/matches").json()
    assert body["unscored"] == []


def test_another_users_search_is_404(client, session, chat):
    get_or_create_default_user(session)
    other = User(email="other@example.com")
    session.add(other)
    session.commit()
    theirs = Search(user_id=other.id, title="theirs")
    session.add(theirs)
    session.commit()
    for method, path in (
        ("get", ""),
        ("delete", ""),
        ("post", "/reread"),
        ("post", "/run"),
        ("post", "/rank"),
        ("get", "/matches"),
        ("post", "/refinements"),
    ):
        response = client.request(
            method, f"/searches/{theirs.id}{path}", json={"text": "x"} if method == "post" else None
        )
        assert response.status_code in (404, 503), (method, path)
    assert client.get("/searches").json() == []


@pytest.mark.parametrize("path", ["/preferences", "/search", "/matches"])
def test_the_old_routes_are_gone(client, path):
    assert client.get(path).status_code in (404, 405)


def test_jobs_default_to_the_latest_search_and_fall_back_to_all(client, session):
    def raw(ext, title):
        return RawJob(
            source="f",
            external_id=ext,
            title=title,
            company="Acme",
            remote=True,
            url=f"https://x/{ext}",
            description="d",
        )

    upsert_jobs(
        session, [raw("a", "AI Engineer"), raw("b", "Data Analyst")], now=datetime(2026, 9, 20)
    )
    assert {j["external_id"] for j in client.get("/jobs").json()} == {"a", "b"}
    search = make_search(session, titles=["AI Engineer"])
    assert [j["external_id"] for j in client.get("/jobs").json()] == ["a"]
    listed = client.get("/jobs", params={"search_id": search.id}).json()
    assert [j["external_id"] for j in listed] == ["a"]
    assert len(client.get("/jobs", params={"all": "true"}).json()) == 2
    assert client.get("/jobs", params={"search_id": 9999}).status_code == 404


def test_run_read_includes_sources(client, session, chat):
    created = _create(client).json()
    entry = {
        "name": "himalayas",
        "state": "searching",
        "fetched": 4,
        "queries_done": 1,
        "queries_total": 3,
        "detail": None,
    }
    run = Run(job="search", search_id=created["id"], sources=[entry])
    session.add(run)
    session.commit()
    session.refresh(run)
    body = client.get(f"/searches/{created['id']}/runs/{run.id}").json()
    # A row written before `notes` existed reads as having none.
    assert body["sources"] == [{**entry, "notes": []}]


def test_run_read_includes_source_notes(client, session, chat):
    created = _create(client).json()
    entry = {
        "name": "indeed",
        "state": "done",
        "fetched": 4,
        "queries_done": 2,
        "queries_total": 2,
        "detail": None,
        "notes": ["not searched in Spain, only 2 searches per run"],
    }
    run = Run(job="search", search_id=created["id"], sources=[entry])
    session.add(run)
    session.commit()
    session.refresh(run)
    body = client.get(f"/searches/{created['id']}/runs/{run.id}").json()
    assert body["sources"] == [entry]


def test_a_question_can_be_read_by_id(client, chat):
    search_id = _create(client).json()["id"]
    response = client.get(f"/searches/{search_id}/questions/level")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "level"
    values = [o["choice"] for o in body["options"]]
    assert values[0] == "intern"
    assert values[-1] == "any"
    assert client.get(f"/searches/{search_id}/questions/nope").status_code == 422


def test_reading_a_question_of_another_users_search_is_404(client, session):
    get_or_create_default_user(session)
    other = User(email="other@example.com")
    session.add(other)
    session.commit()
    theirs = Search(user_id=other.id, title="theirs")
    session.add(theirs)
    session.commit()
    assert client.get(f"/searches/{theirs.id}/questions/level").status_code == 404


def test_job_read_carries_the_work_mode(client, session):
    remote = _job(session, "r")
    hybrid = Job(
        source="t",
        external_id="h",
        title="AI Engineer (Hybrid)",
        company="Acme",
        remote=False,
        url="https://x/h",
        description="d",
        content_hash="h-h",
    )
    session.add(hybrid)
    session.commit()
    modes = {j["external_id"]: j["work_mode"] for j in client.get("/jobs?all=true").json()}
    assert modes == {remote.external_id: "remote", "h": "hybrid"}


def test_list_searches_counts_the_scored_jobs_not_dismissed(client, session):
    from jobscout.models import Job, Match
    from jobscout.pipeline.users import get_or_create_default_user
    from tests.helpers import make_search

    user = get_or_create_default_user(session)
    search, other = make_search(session, title="A"), make_search(session, title="B")
    rows = [(None, "low"), (80, "new"), (70, "saved"), (60, "dismissed")]
    for n, (score, status) in enumerate(rows):
        job = Job(
            source="t",
            external_id=str(n),
            title="T",
            company="C",
            description="d",
            url=f"https://x/{n}",
            content_hash=str(n),
        )
        session.add(job)
        session.commit()
        session.add(
            Match(
                job_id=job.id,
                user_id=user.id,
                search_id=search.id,
                similarity=0.5,
                score=score,
                status=status,
            )
        )
    session.commit()
    counts = {item["title"]: item["match_count"] for item in client.get("/searches").json()}
    assert counts == {"A": 2, "B": 0}
    assert other.id is not None


def test_rename_a_search(client, chat):
    created = _create(client).json()
    response = client.patch(f"/searches/{created['id']}", json={"title": "Remote ML"})
    assert response.status_code == 200
    assert response.json()["title"] == "Remote ML"
    assert client.get("/searches").json()[0]["title"] == "Remote ML"
    assert client.patch(f"/searches/{created['id']}", json={"title": " "}).status_code == 422
    assert client.patch("/searches/999", json={"title": "x"}).status_code == 404


def test_export_a_search_as_csv(client, session):
    import csv
    import io

    from jobscout.models import Job, Match
    from jobscout.pipeline.users import get_or_create_default_user
    from tests.helpers import make_search

    user = get_or_create_default_user(session)
    search = make_search(session, title="Dados · remoto")
    other = make_search(session, title="Other")
    rows = [("Data Engineer", "=HYPERLINK(evil)", 60, "saved"), ("ML Engineer", "Acme", 90, "new")]
    for n, (title, company, score, status) in enumerate(rows):
        job = Job(
            source="indeed",
            external_id=str(n),
            title=title,
            company=company,
            description="d",
            remote=True,
            url=f"https://x/{n}",
            content_hash=str(n),
        )
        session.add(job)
        session.commit()
        session.add(
            Match(
                job_id=job.id,
                user_id=user.id,
                search_id=search.id,
                similarity=0.5,
                score=score,
                status=status,
                matched_skills=["Python", "SQL"],
            )
        )
    session.add(Match(job_id=job.id, user_id=user.id, search_id=other.id, similarity=0.5, score=10))
    session.commit()

    response = client.get(f"/searches/{search.id}/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="jobscout-dados-remoto.csv"' in response.headers["content-disposition"]
    table = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert table[0][:4] == ["title", "company", "location", "work_mode"]
    assert [row[0] for row in table[1:]] == ["ML Engineer", "Data Engineer"]
    by_title = {row[0]: dict(zip(table[0], row, strict=True)) for row in table[1:]}
    assert by_title["Data Engineer"]["company"] == "'=HYPERLINK(evil)"
    assert by_title["Data Engineer"]["status"] == "saved"
    assert by_title["ML Engineer"]["matched_skills"] == "Python; SQL"
    assert client.get("/searches/999/export.csv").status_code == 404


def test_stop_asks_the_running_search_to_stop(client, chat, fake_scheduler):
    created = _create(client).json()
    fake_scheduler.running = (created["id"], 5)
    response = client.post(f"/searches/{created['id']}/stop")
    assert response.status_code == 202
    assert response.json() == {"stopping": True}
    assert fake_scheduler.stopped == [created["id"]]


def test_stop_when_nothing_runs_is_harmless(client, chat, fake_scheduler):
    # The run may end between the page drawing Stop and the click reaching the server.
    created = _create(client).json()
    response = client.post(f"/searches/{created['id']}/stop")
    assert response.status_code == 202
    assert response.json() == {"stopping": False}


def test_stop_on_an_unknown_search_is_404(client, chat, fake_scheduler):
    assert client.post("/searches/999/stop").status_code == 404
    assert fake_scheduler.stopped == []


def test_a_stopped_run_reads_back_with_its_stopped_sources(client, session, chat):
    created = _create(client).json()
    source = {
        "name": "himalayas",
        "state": "stopped",
        "fetched": 3,
        "queries_done": 1,
        "queries_total": 2,
        "detail": None,
        "notes": [],
    }
    run = Run(job="search", search_id=created["id"], counters={"stopped": 1}, sources=[source])
    session.add(run)
    session.commit()
    response = client.get(f"/searches/{created['id']}/runs/{run.id}")
    assert response.status_code == 200
    assert response.json()["sources"][0]["state"] == "stopped"
    assert response.json()["counters"]["stopped"] == 1

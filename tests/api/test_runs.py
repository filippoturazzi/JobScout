from datetime import timedelta

from jobscout.models import Run
from jobscout.models.base import utcnow


def test_runs_returns_newest_first(client, session):
    session.add(Run(job="ingest", started_at=utcnow() - timedelta(hours=2), ok=True))
    session.add(Run(job="match", started_at=utcnow() - timedelta(hours=1), ok=True))
    session.commit()

    body = client.get("/runs").json()

    assert [row["job"] for row in body] == ["match", "ingest"]


def test_runs_filters_by_job(client, session):
    session.add(Run(job="ingest", ok=True))
    session.add(Run(job="match", ok=True))
    session.commit()

    body = client.get("/runs", params={"job": "ingest"}).json()

    assert [row["job"] for row in body] == ["ingest"]


def test_runs_exposes_counters_and_errors(client, session):
    session.add(Run(job="match", ok=False, error="RuntimeError: 429", counters={"evaluated": 0}))
    session.commit()

    row = client.get("/runs").json()[0]

    assert (row["ok"], row["error"], row["counters"]) == (
        False,
        "RuntimeError: 429",
        {"evaluated": 0},
    )


def test_runs_honours_limit(client, session):
    for _ in range(5):
        session.add(Run(job="ingest", ok=True))
    session.commit()

    assert len(client.get("/runs", params={"limit": 2}).json()) == 2


def test_runs_rejects_an_unknown_job_name(client):
    """A typo must be a 422, not an empty list that reads like 'it never ran'."""
    assert client.get("/runs", params={"job": "ingset"}).status_code == 422


def test_runs_break_started_at_ties_by_id(client, session):
    # Behavioural smoke test: does not pin the query plan (see test_list_runs_orders_by...).
    """Two rows sharing a timestamp must come back newest-id first, so `limit` keeps the newer."""
    stamp = utcnow()
    session.add(Run(job="ingest", started_at=stamp, ok=True))
    session.add(Run(job="match", started_at=stamp, ok=True))
    session.commit()

    full = client.get("/runs").json()
    limited = client.get("/runs", params={"limit": 1}).json()

    assert [row["job"] for row in full] == ["match", "ingest"]
    assert [row["job"] for row in limited] == ["match"]


def test_runs_serializes_an_in_flight_run(client, session):
    session.add(Run(job="ingest", ok=False, finished_at=None))
    session.commit()

    row = client.get("/runs").json()[0]

    assert (row["finished_at"], row["ok"]) == (None, False)


def test_runs_round_trips_empty_counters(client, session):
    session.add(Run(job="ingest", ok=True, counters={}))
    session.commit()

    assert client.get("/runs").json()[0]["counters"] == {}


def test_runs_break_ties_by_id_under_a_job_filter(client, session):
    # Behavioural smoke test: does not pin the query plan (see test_list_runs_orders_by...).
    """Filtering by job changes the query plan; the tie-break must hold there too."""
    stamp = utcnow()
    for _ in range(3):
        session.add(Run(job="ingest", started_at=stamp, ok=True))
    session.commit()

    ids = [row["id"] for row in client.get("/runs", params={"job": "ingest"}).json()]
    limited = client.get("/runs", params={"job": "ingest", "limit": 1}).json()

    assert ids == sorted(ids, reverse=True)
    assert [row["id"] for row in limited] == [ids[0]]

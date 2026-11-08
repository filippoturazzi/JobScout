import importlib.util
from pathlib import Path

from sqlmodel import Session, col, select

from jobscout.db import create_engine_from_url
from jobscout.models import Run, Search
from jobscout.pipeline import conversation as conv
from jobscout.pipeline.run import count_waiting, list_matches, list_my_jobs
from jobscout.pipeline.searches import conversation_of
from jobscout.pipeline.users import get_or_create_default_user

SCRIPT = Path(__file__).parent.parent / "scripts" / "seed_demo.py"


def _load():
    spec = importlib.util.spec_from_file_location("seed_demo", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _latest_run(session: Session, search_id: int) -> Run:
    return session.exec(
        select(Run).where(Run.search_id == search_id).order_by(col(Run.started_at).desc()).limit(1)
    ).one()


def test_seed_builds_every_state(tmp_path, capsys):
    path = tmp_path / "demo.db"
    assert _load().main([str(path)]) == 0
    assert "uv run jobscout serve" in capsys.readouterr().out

    engine = create_engine_from_url(f"sqlite:///{path.as_posix()}")
    with Session(engine) as session:
        user = get_or_create_default_user(session)
        assert user.id is not None
        by_title = {s.title: s for s in session.exec(select(Search)).all()}
        assert len(by_title) == 5

        one = by_title["Junior AI Engineer"]
        assert one.id is not None
        found = list_matches(session, one.id, limit=100)
        scores = [m.score for m, _ in found]
        assert len(found) == 12 and scores == sorted(scores, reverse=True)
        assert count_waiting(session, one.id) == 9

        jobs = list_my_jobs(session, user.id)
        assert jobs.counts["saved"] == 2
        assert jobs.counts["applied"] == 1
        shared = [j for j in jobs.items if j.job.title == "AI Engineer (Python)"]
        assert len(shared) == 1 and len(shared[0].searches) == 2

        three = by_title["Data analyst for a friend"]
        assert three.id is not None
        run = _latest_run(session, three.id)
        assert run.finished_at is not None
        assert [s["state"] for s in run.sources] == ["done", "failed"]
        assert run.sources[1]["detail"] == "SourceBlocked: 429 Too Many Requests"
        assert list_matches(session, three.id) == []
        assert count_waiting(session, three.id) == 0

        four = by_title["Frontend in Lisbon"]
        assert conv.pending(conversation_of(four)) == ["location"]

        five = by_title["Data engineer"]
        assert five.id is not None
        interrupted = _latest_run(session, five.id)
        assert interrupted.finished_at is None and not interrupted.ok
    engine.dispose()


def test_seed_refuses_an_existing_file(tmp_path, capsys):
    path = tmp_path / "demo.db"
    path.write_text("keep me")
    assert _load().main([str(path)]) == 1
    assert path.read_text() == "keep me"
    assert "already exists" in capsys.readouterr().err

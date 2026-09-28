import logging

import httpx
import respx
from sqlmodel import Session, select
from typer.testing import CliRunner

from jobscout import cli
from jobscout.config import Settings
from jobscout.db import get_engine, init_db
from jobscout.models import Job, Match, User
from jobscout.pipeline.users import get_or_create_default_user, update_preferences
from jobscout.sources.arbeitnow import BASE_URL
from tests.conftest import load_fixture

runner = CliRunner()


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'test.db'}")


@respx.mock
def test_fetch_then_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(200, json=load_fixture("arbeitnow_sample.json"))
    )

    result = runner.invoke(cli.app, ["fetch"])
    assert result.exit_code == 0, result.output
    assert "arbeitnow" in result.output
    assert "created=3" in result.output

    with Session(get_engine(_settings(tmp_path))) as s:
        assert s.exec(select(User)).all() == [], "fetch must not bootstrap a user"

    result = runner.invoke(cli.app, ["jobs"])
    assert result.exit_code == 0, result.output
    assert "AI Developer (m/f/d)" in result.output
    assert "Partspace" in result.output


@respx.mock
def test_fetch_reports_source_error_and_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    respx.get(url__startswith=BASE_URL).mock(return_value=httpx.Response(500))

    result = runner.invoke(cli.app, ["fetch"])
    assert result.exit_code == 1
    assert "HTTPStatusError" in result.output


def test_fetch_unknown_source_exits_with_code_2(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        sources="arbeitnow,nope",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    result = runner.invoke(cli.app, ["fetch"])
    assert result.exit_code == 2
    assert "Unknown source" in result.output


def test_jobs_on_empty_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    result = runner.invoke(cli.app, ["jobs"])
    assert result.exit_code == 0
    assert "No jobs" in result.output


def test_serve_calls_uvicorn(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    calls = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **kw: calls.update(kw, app=a[0]))
    result = runner.invoke(cli.app, ["serve", "--port", "9001"])
    assert result.exit_code == 0
    assert calls["app"] == "jobscout.api.app:app"
    assert calls["port"] == 9001


def test_serve_uses_settings_defaults_and_honors_port_zero(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        api_host="0.0.0.0",
        api_port=8123,
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    calls: list[dict] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **kw: calls.append({**kw, "app": a[0]}))

    assert runner.invoke(cli.app, ["serve"]).exit_code == 0
    assert calls[-1] == {
        "app": "jobscout.api.app:app",
        "host": "0.0.0.0",
        "port": 8123,
        "reload": False,
    }

    result = runner.invoke(cli.app, ["serve", "--port", "0", "--host", "127.0.0.1", "--reload"])
    assert result.exit_code == 0
    assert calls[-1] == {
        "app": "jobscout.api.app:app",
        "host": "127.0.0.1",
        "port": 0,
        "reload": True,
    }


def test_match_without_provider_key_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with Session(get_engine(_settings(tmp_path))) as session:
        init_db(get_engine(_settings(tmp_path)))
        user = get_or_create_default_user(session)
        update_preferences(session, user.id, {"profile_summary": "Python engineer."})
        session.add(
            Job(
                source="t",
                external_id="a",
                title="AI Engineer",
                company="Acme",
                remote=True,
                url="https://x/a",
                description="Python LLM work.",
                content_hash="h",
            )
        )
        session.commit()

    result = runner.invoke(cli.app, ["match"])

    assert result.exit_code == 2
    assert "GOOGLE_API_KEY" in result.output


def test_match_reports_when_there_is_no_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    result = runner.invoke(cli.app, ["match"])
    assert result.exit_code == 0
    assert "profile" in result.output.lower()


def test_matches_lists_scored_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    engine = get_engine(_settings(tmp_path))
    init_db(engine)
    with Session(engine) as session:
        user = get_or_create_default_user(session)
        job = Job(
            source="t",
            external_id="a",
            title="AI Engineer",
            company="Acme",
            remote=True,
            url="https://x/a",
            description="d",
            content_hash="h",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        session.add(
            Match(
                job_id=job.id,
                user_id=user.id,
                similarity=0.8,
                score=91,
                reasoning="Strong fit.",
                status="new",
            )
        )
        session.commit()

    result = runner.invoke(cli.app, ["matches"])

    assert result.exit_code == 0
    assert "91" in result.output and "AI Engineer" in result.output


def test_matches_on_empty_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    result = runner.invoke(cli.app, ["matches"])
    assert result.exit_code == 0
    assert "No matches" in result.output


def test_match_dry_run_lists_candidates_without_calling_the_llm(tmp_path, monkeypatch):
    import jobscout.pipeline.matching as matching_module
    from tests.matching.fakes import DeterministicFakeEmbedding

    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    engine = get_engine(_settings(tmp_path))
    init_db(engine)
    with Session(engine) as session:
        user = get_or_create_default_user(session)
        update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
        session.add(
            Job(
                source="t",
                external_id="a",
                title="AI Engineer",
                company="Acme",
                remote=True,
                url="https://x/a",
                description="Python LLM work.",
                content_hash="h",
            )
        )
        session.commit()

    def _explode(_settings):
        raise AssertionError("a dry run must not construct a chat model")

    monkeypatch.setattr(matching_module, "chat_model", _explode)
    monkeypatch.setattr(
        matching_module, "embeddings", lambda _settings: DeterministicFakeEmbedding(size=8)
    )

    result = runner.invoke(cli.app, ["match", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Would evaluate 1 of 1 candidates" in result.output
    assert "AI Engineer" in result.output


def test_match_scores_and_persists_a_candidate_end_to_end(tmp_path, monkeypatch):
    """The whole non-dry-run path: CLI -> run_match -> graph -> persisted row -> summary."""
    import jobscout.pipeline.matching as matching_module
    from tests.matching.fakes import CountingChatModel, DeterministicFakeEmbedding

    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        embedding_dim=8,
        similarity_threshold=-1.0,  # the fake vectors carry no meaningful floor
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    engine = get_engine(settings)
    init_db(engine)
    with Session(engine) as session:
        user = get_or_create_default_user(session)
        update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
        session.add(
            Job(
                source="t",
                external_id="a",
                title="AI Engineer",
                company="Acme",
                remote=True,
                url="https://x/a",
                description="Python LLM work.",
                content_hash="h",
            )
        )
        session.commit()

    monkeypatch.setattr(matching_module, "chat_model", lambda _settings: CountingChatModel())
    monkeypatch.setattr(
        matching_module, "embeddings", lambda _settings: DeterministicFakeEmbedding(size=8)
    )

    result = runner.invoke(cli.app, ["match"])

    assert result.exit_code == 0, result.output
    assert "candidates=1 evaluated=1 skipped_low=0 embedded=1 pending=0 errors=0" in result.output
    with Session(engine) as session:
        row = session.exec(select(Match)).one()
        assert row.score == 75 and row.status == "new"
        assert row.reasoning and row.llm_model == settings.llm_model


def test_match_reports_a_provider_runtime_error_without_a_traceback(tmp_path, monkeypatch):
    import jobscout.pipeline.matching as matching_module

    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    engine = get_engine(_settings(tmp_path))
    init_db(engine)
    with Session(engine) as session:
        user = get_or_create_default_user(session)
        update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
        session.add(
            Job(
                source="t",
                external_id="a",
                title="AI Engineer",
                company="Acme",
                remote=True,
                url="https://x/a",
                description="Python LLM work.",
                content_hash="h",
            )
        )
        session.commit()

    def _rate_limited(_settings):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(matching_module, "embeddings", _rate_limited)

    result = runner.invoke(cli.app, ["match"])

    # 2 = the provider could not be used, distinct from 1 = it ran and everything failed.
    assert result.exit_code == 2
    assert "Error: RuntimeError: 429 RESOURCE_EXHAUSTED" in result.output
    assert "Traceback" not in result.output


def test_match_exits_1_when_every_candidate_failed(tmp_path, monkeypatch):
    from jobscout.pipeline.matching import MatchRun

    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        cli,
        "run_match",
        lambda *a, **kw: MatchRun(candidates=1, errors=["job 1: RuntimeError: boom"]),
    )

    result = runner.invoke(cli.app, ["match"])

    assert result.exit_code == 1
    assert "boom" in result.output


def test_match_keeps_the_stack_out_of_the_terminal(tmp_path, monkeypatch, caplog):
    """The one-line Error is the contract; a stack belongs at DEBUG, not in the user's face.

    CliRunner's `result.output` does not capture logging, so asserting on it alone passed
    while a real `jobscout match` printed a full traceback above the clean message.
    """
    import jobscout.pipeline.matching as matching_module

    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    engine = get_engine(_settings(tmp_path))
    init_db(engine)
    with Session(engine) as session:
        user = get_or_create_default_user(session)
        update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
        session.add(
            Job(
                source="t",
                external_id="a",
                title="AI Engineer",
                company="Acme",
                remote=True,
                url="https://x/a",
                description="Python LLM work.",
                content_hash="h",
            )
        )
        session.commit()

    def _rate_limited(_settings):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(matching_module, "embeddings", _rate_limited)

    with caplog.at_level(logging.WARNING, logger="jobscout.cli"):
        result = runner.invoke(cli.app, ["match"])

    assert result.exit_code == 2
    assert [record.message for record in caplog.records] == []


def test_matches_says_why_the_list_is_empty_when_a_filter_hid_everything(tmp_path, monkeypatch):
    """`min_score` excluding every row is not the same as never having matched."""
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    engine = get_engine(_settings(tmp_path))
    init_db(engine)
    with Session(engine) as session:
        user = get_or_create_default_user(session)
        job = Job(
            source="t",
            external_id="a",
            title="AI Engineer",
            company="Acme",
            remote=True,
            url="https://x/a",
            description="Python LLM work.",
            content_hash="h",
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        session.add(Match(job_id=job.id, user_id=user.id, similarity=0.6, score=10))
        session.commit()

    result = runner.invoke(cli.app, ["matches", "--min-score", "60"])

    assert result.exit_code == 0
    assert "60" in result.output, "the message must name the floor that hid the rows"
    assert "Run `jobscout match`" not in result.output


def test_repair_descriptions_reports_what_it_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    engine = get_engine(_settings(tmp_path))
    init_db(engine)
    mixed = "&lt;p&gt;Python work.&lt;/p&gt;<p>Find more</p>"
    with Session(engine) as session:
        session.add(
            Job(
                source="t",
                external_id="a",
                title="AI Engineer",
                company="Acme",
                remote=True,
                url="https://x/a",
                description="<p>Python work.</p> Find more",
                content_hash="h",
                embedding=b"\x00\x00\x00\x00",
                raw={"description": mixed},
            )
        )
        session.commit()

    result = runner.invoke(cli.app, ["repair-descriptions"])

    assert result.exit_code == 0
    assert "repaired=1" in result.output
    with Session(engine) as session:
        job = session.exec(select(Job)).one()
        assert job.description == "Python work. Find more"
        assert job.embedding is None

import logging
from datetime import timedelta

import httpx
import respx
from sqlmodel import Session, select
from typer.testing import CliRunner

from jobscout import cli
from jobscout.config import Settings
from jobscout.db import create_engine_from_url, get_engine, init_db, needs_upgrade
from jobscout.models import Job, Match, Search, User
from jobscout.models.base import utcnow
from jobscout.pipeline.search import SearchProgress, SearchResult
from jobscout.sources import registry
from jobscout.sources.arbeitnow import BASE_URL
from tests.conftest import load_fixture
from tests.helpers import fetched, make_search

runner = CliRunner()


def _db(tmp_path) -> Session:
    engine = get_engine(_settings(tmp_path))
    init_db(engine)
    return Session(engine)


def _settings(tmp_path) -> Settings:
    # These tests fetch from Arbeitnow via respx, so name it rather than rely on the default.
    return Settings(
        _env_file=None, database_url=f"sqlite:///{tmp_path / 'test.db'}", sources="arbeitnow"
    )


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
    assert "merged=0" in result.output

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
        search = make_search(session, "Python engineer.")
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
        fetched(session, search, *session.exec(select(Job)).all())

    result = runner.invoke(cli.app, ["match"])

    assert result.exit_code == 2
    assert "GOOGLE_API_KEY" in result.output


def test_match_reports_when_the_search_has_no_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    with _db(tmp_path) as session:
        make_search(session)
    result = runner.invoke(cli.app, ["match"])
    assert result.exit_code == 0
    assert "profile" in result.output.lower()


def test_matches_lists_scored_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    engine = get_engine(_settings(tmp_path))
    init_db(engine)
    with Session(engine) as session:
        search = make_search(session)
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
                user_id=search.user_id,
                search_id=search.id,
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


def test_matches_on_a_search_with_no_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    with _db(tmp_path) as session:
        make_search(session)
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
        search = make_search(session, "Python LLM engineer.")
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
        fetched(session, search, *session.exec(select(Job)).all())

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
        search = make_search(session, "Python LLM engineer.")
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
        fetched(session, search, *session.exec(select(Job)).all())

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
        search = make_search(session, "Python LLM engineer.")
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
        fetched(session, search, *session.exec(select(Job)).all())

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
    with _db(tmp_path) as session:
        make_search(session)

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
        search = make_search(session, "Python LLM engineer.")
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
        fetched(session, search, *session.exec(select(Job)).all())

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
        search = make_search(session)
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
        session.add(
            Match(
                job_id=job.id,
                user_id=search.user_id,
                search_id=search.id,
                similarity=0.6,
                score=10,
            )
        )
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


def _fake_search(scores: list[int], ok: bool = True, errors: list[str] | None = None):
    """Stands in for `run_search`: writes scored matches the way a real run would."""

    def search(session, settings, search_id, deps=None, run_id=None, on_progress=None):
        owner = session.get(Search, search_id)
        for i, score in enumerate(scores):
            job = Job(
                source="t",
                external_id=f"j{i}",
                title=f"Role {score}",
                company="Acme",
                remote=True,
                url=f"https://x/{i}",
                description="d",
                content_hash=f"h{i}",
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            session.add(
                Match(
                    job_id=job.id,
                    user_id=owner.user_id,
                    search_id=search_id,
                    similarity=0.8,
                    score=score,
                    status="new",
                )
            )
        session.commit()
        return SearchResult(
            run_id=1,
            ok=ok,
            terms=["python developer"],
            fetched=len(scores),
            sources_ok=1 if ok else 0,
            sources_failed=0 if ok else 1,
            candidates=len(scores),
            evaluated=len(scores),
            errors=errors or [],
        )

    return search


def test_search_command_prints_ranked_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(cli, "run_search", _fake_search([40, 90, 65]))
    with _db(tmp_path) as session:
        make_search(session)
    result = runner.invoke(cli.app, ["search"])
    assert result.exit_code == 0, result.output
    assert "fetched=3" in result.output
    ranked = [line for line in result.output.splitlines() if line.startswith("[")]
    assert ranked == ["[90] Role 90 — Acme", "[65] Role 65 — Acme", "[40] Role 40 — Acme"]


def test_search_command_reports_dormant_sources(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        sources="himalayas,remotive",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setitem(registry.SOURCE_MISSING_CREDENTIALS, "remotive", lambda s: ["FAKE_KEY"])
    monkeypatch.setattr(cli, "run_search", _fake_search([]))
    init_db(get_engine(settings))
    with Session(get_engine(settings)) as session:
        make_search(session)
    result = runner.invoke(cli.app, ["search"])
    assert "remotive: dormant (missing FAKE_KEY)" in result.output


def test_a_failed_search_prints_why_and_exits_1(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.setattr(
        cli, "run_search", _fake_search([], ok=False, errors=["ValueError: nothing to search for"])
    )
    with _db(tmp_path) as session:
        make_search(session)
    result = runner.invoke(cli.app, ["search"])
    assert result.exit_code == 1
    assert "nothing to search for" in result.output


def test_search_command_prints_progress_while_it_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    finish = _fake_search([80])

    def search(session, settings, search_id, deps=None, run_id=None, on_progress=None):
        assert on_progress is not None, "the command must ask for progress"
        on_progress(SearchProgress(stage="terms", terms=["python developer"]))
        on_progress(SearchProgress(stage="source", source="linkedin", term="python", fetched=10))
        on_progress(
            SearchProgress(
                stage="source", source="indeed", term="python", error="SourceBlocked: 429"
            )
        )
        on_progress(SearchProgress(stage="scoring", total=40))
        on_progress(SearchProgress(stage="evaluated", done=1, total=25))
        return finish(session, settings, search_id)

    monkeypatch.setattr(cli, "run_search", search)
    with _db(tmp_path) as session:
        make_search(session)
    result = runner.invoke(cli.app, ["search"])
    lines = result.output.splitlines()
    expected = [
        "terms: python developer",
        "linkedin: 10 postings for 'python'",
        "indeed: failed for 'python': SourceBlocked: 429",
        "scoring 40 candidates (embeddings first, then up to 15 LLM evaluations)",
        "  evaluated 1/25",
    ]
    positions = [lines.index(line) for line in expected]
    assert positions == sorted(positions)
    assert positions[-1] < lines.index("[80] Role 80 — Acme"), "progress comes before the ranking"


def test_upgrade_db_command_backs_up_and_upgrades(old_db, tmp_path, monkeypatch):
    settings = Settings(_env_file=None, database_url=old_db)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    result = runner.invoke(cli.app, ["upgrade-db"])

    assert result.exit_code == 0, result.output
    (backup,) = tmp_path.glob("old.db.bak-*")
    assert str(backup) in result.output
    assert "searches=1 matches=2 runs=1" in result.output
    with Session(get_engine(settings)) as session:
        assert len(session.exec(select(Search)).all()) == 1

    again = runner.invoke(cli.app, ["upgrade-db"])
    assert again.exit_code == 0, again.output
    assert "Already up to date." in again.output
    assert len(list(tmp_path.glob("old.db.bak-*"))) == 1, "no backup when nothing changes"


def test_upgrade_db_refuses_postgres(old_db, monkeypatch):
    engine = create_engine_from_url(old_db)
    monkeypatch.setattr(engine.dialect, "name", "postgresql")
    settings = Settings(_env_file=None, database_url="postgresql://u:p@localhost/jobscout")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "get_engine", lambda _settings: engine)

    result = runner.invoke(cli.app, ["upgrade-db"])

    assert result.exit_code == 2
    assert "SQLite" in result.output
    assert "Traceback" not in result.output


def test_upgrade_db_refuses_to_overwrite_a_backup(old_db, monkeypatch):
    settings = Settings(_env_file=None, database_url=old_db)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    def taken(url, now):
        raise FileExistsError("Backup target already exists: old.db.bak-1")

    monkeypatch.setattr(cli, "backup_sqlite", taken)

    result = runner.invoke(cli.app, ["upgrade-db"])

    assert result.exit_code == 2
    assert "Backup target already exists: old.db.bak-1" in result.output
    assert needs_upgrade(get_engine(settings)) is True, "no conversion without a backup"


def test_commands_on_an_old_database_say_to_upgrade(old_db, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None, database_url=old_db))

    result = runner.invoke(cli.app, ["jobs"])

    assert result.exit_code == 2
    assert "jobscout upgrade-db" in result.output


def _older(session, search, days: int = 1) -> None:
    search.last_used_at = utcnow() - timedelta(days=days)
    session.add(search)
    session.commit()


def test_searches_lists_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    with _db(tmp_path) as session:
        old = make_search(session, title="Old one")
        new = make_search(session, title="New one")
        _older(session, old, 2)
        old_id, new_id = old.id, new.id

    result = runner.invoke(cli.app, ["searches"])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith(str(new_id)) and "New one" in lines[0]
    assert lines[1].startswith(str(old_id)) and "Old one" in lines[1]


def test_searches_when_there_are_none(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    result = runner.invoke(cli.app, ["searches"])
    assert result.exit_code == 0
    assert "No searches yet. Start one in the page: jobscout serve" in result.output


def _recording_search(calls: list[int]):
    inner = _fake_search([])

    def search(session, settings, search_id, **kw):
        calls.append(search_id)
        return inner(session, settings, search_id, **kw)

    return search


def test_search_defaults_to_the_latest_search(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    calls: list[int] = []
    monkeypatch.setattr(cli, "run_search", _recording_search(calls))
    with _db(tmp_path) as session:
        old = make_search(session, title="Old")
        new = make_search(session, title="New")
        _older(session, old)
        new_id = new.id

    result = runner.invoke(cli.app, ["search"])

    assert result.exit_code == 0, result.output
    assert calls == [new_id]


def test_search_takes_an_explicit_search(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    calls: list[int] = []
    monkeypatch.setattr(cli, "run_search", _recording_search(calls))
    with _db(tmp_path) as session:
        old = make_search(session, title="Old")
        make_search(session, title="New")
        _older(session, old)
        old_id = old.id

    result = runner.invoke(cli.app, ["search", "--search", str(old_id)])

    assert result.exit_code == 0, result.output
    assert calls == [old_id]


def test_search_with_no_searches_says_how_to_start(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    calls: list[int] = []
    monkeypatch.setattr(cli, "run_search", _recording_search(calls))

    result = runner.invoke(cli.app, ["search"])

    assert result.exit_code == 2
    assert "jobscout serve" in result.output
    assert calls == []


def test_match_with_no_searches_says_how_to_start(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    result = runner.invoke(cli.app, ["match"])
    assert result.exit_code == 2
    assert "jobscout serve" in result.output


def test_matches_with_no_searches_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    result = runner.invoke(cli.app, ["matches"])
    assert result.exit_code == 0
    assert "No searches yet" in result.output


def test_an_unknown_search_id_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    with _db(tmp_path) as session:
        make_search(session)
    for command in ("search", "match", "matches", "jobs"):
        result = runner.invoke(cli.app, [command, "--search", "999"])
        assert result.exit_code == 2, command
        assert "No search 999." in result.output


def test_jobs_with_no_searches_lists_every_active_job(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    with _db(tmp_path) as session:
        session.add(
            Job(
                source="t",
                external_id="a",
                title="AI Engineer",
                company="Acme",
                remote=True,
                url="https://x/a",
                description="d",
                content_hash="h",
            )
        )
        session.commit()

    result = runner.invoke(cli.app, ["jobs"])

    assert result.exit_code == 0, result.output
    assert "AI Engineer" in result.output

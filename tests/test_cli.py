import httpx
import respx
from typer.testing import CliRunner

from jobscout import cli
from jobscout.config import Settings
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

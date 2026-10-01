"""Operator-config behaviour of the real entry points, which only run at import time.

Each case runs in a fresh interpreter in an empty directory (so no stray .env is read):
the logging setup and the config validation both happen on import, and a test process that
has already imported the app cannot observe them.
"""

import subprocess
import sys

import pytest

APP = "jobscout.api.app"
CLI = "jobscout.cli"


def _run(tmp_path, code: str, **env: str) -> subprocess.CompletedProcess[str]:
    import os

    full_env = {k: v for k, v in os.environ.items() if k not in {"LOG_LEVEL", "SCHEDULER_ENABLED"}}
    full_env.update(env)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("module", [APP, CLI])
def test_a_bad_log_level_stops_both_entry_points(tmp_path, module):
    result = _run(tmp_path, f"import {module}", LOG_LEVEL="chatty")

    assert result.returncode != 0
    assert "Invalid configuration" in result.stderr
    assert "CRITICAL" in result.stderr, "names the accepted values"
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("module", [APP, CLI])
def test_a_zero_interval_stops_both_entry_points_readably(tmp_path, module):
    result = _run(tmp_path, f"import {module}", INGEST_INTERVAL_MINUTES="0")

    assert result.returncode != 0
    assert "Invalid configuration" in result.stderr
    assert "ingest_interval_minutes" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("module", [APP, CLI])
def test_log_level_is_applied_by_every_entry_point(tmp_path, module):
    code = f"import logging, {module}; print(logging.getLogger().level)"

    result = _run(tmp_path, code, LOG_LEVEL="info")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(20)


def test_log_level_defaults_to_warning_for_the_app(tmp_path):
    result = _run(tmp_path, f"import logging, {APP}; print(logging.getLogger().level)")

    assert result.stdout.strip() == "30"

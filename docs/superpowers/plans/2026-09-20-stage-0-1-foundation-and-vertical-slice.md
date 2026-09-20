# JobScout Stages 0–1: Foundation + Vertical Slice (no AI) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `uv`-managed Python package `jobscout` that fetches real jobs from Arbeitnow into SQLite with dedup/liveness tracking, exposes them through a Typer CLI and a FastAPI API filtered by a single user's preferences, with green CI and no network access in tests.

**Architecture:** `sources/` turns HTTP into `RawJob`s (no DB). `pipeline/` composes: `ingest` upserts `RawJob` → `Job`, `filters` applies deterministic preference rules, `users` bootstraps the fixed user, `run` wires them. `cli.py` and `api/` are thin shells over `pipeline`. Operator config lives in `config.Settings` (env); user preferences live in the `UserPreferences` table.

**Tech Stack:** Python 3.12, uv, SQLModel (SQLAlchemy 2 + Pydantic 2), pydantic-settings, httpx, FastAPI, uvicorn, Typer, pytest, respx, ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-19-jobscout-design.md`

## Global Constraints

- Python `>=3.12`; `.python-version` pins `3.12`. The machine's system Python is 3.14 — never use it; always go through `uv run`.
- Package name `jobscout`, src-layout: code in `src/jobscout/`, tests in `tests/`.
- Tests never touch the network. HTTP is mocked with `respx`; DB is SQLite (in-memory or `tmp_path`).
- Real-network tests carry `@pytest.mark.integration` and are deselected by default (`addopts = "-m 'not integration'"`).
- Operator config comes only from `jobscout.config.Settings` (env / `.env`). User preferences come only from the `UserPreferences` table. Never mix.
- Dependency direction: `sources` → no DB imports. `pipeline` is the only module importing both `sources` and `models`. `api`/`cli` import `pipeline`, never `sources` directly (except the registry via `pipeline`).
- All datetimes are **naive UTC** (`jobscout.models.base.utcnow()`); SQLite drops tzinfo, so storing aware datetimes would make comparisons fail.
- Code, comments, docstrings, commit messages in English. Line endings LF (`.gitattributes` + ruff `line-ending = "lf"`).
- `ruff check .` and `ruff format --check .` must pass before every commit.
- Every commit message ends with the trailer line: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- Conventional commit prefixes: `feat:`, `test:`, `chore:`, `ci:`, `docs:`.
- Arbeitnow API terms (from its `meta.terms`): free public API, do not abuse, link back to arbeitnow.com. Default `arbeitnow_max_pages = 2` (250 jobs/page) and a descriptive `User-Agent`.

---

## File Structure

```
.gitattributes                         LF normalization
.python-version                        3.12
pyproject.toml                         project metadata, deps, ruff, pytest, entry point
LICENSE                                MIT
README.md                              what it is, quick start, dev commands
.env.example                           documented operator variables
.github/workflows/ci.yml               ruff + pytest on push/PR
src/jobscout/__init__.py               __version__
src/jobscout/config.py                 Settings (pydantic-settings) + get_settings()
src/jobscout/models/__init__.py        re-exports
src/jobscout/models/base.py            utcnow(), TimestampMixin
src/jobscout/models/user.py            User, UserPreferences
src/jobscout/models/job.py             Job
src/jobscout/db.py                     create_engine_from_url(), init_db(), get_engine()
src/jobscout/sources/__init__.py
src/jobscout/sources/base.py           RawJob, SearchQuery, JobSource protocol
src/jobscout/sources/text.py           html_to_text()
src/jobscout/sources/arbeitnow.py      ArbeitnowSource
src/jobscout/sources/registry.py       SOURCE_FACTORIES, build_sources()
src/jobscout/pipeline/__init__.py
src/jobscout/pipeline/ingest.py        content_hash(), upsert_jobs(), ingest(), IngestResult
src/jobscout/pipeline/filters.py       job_matches_preferences(), filter_jobs()
src/jobscout/pipeline/users.py         get_or_create_default_user(), update_preferences()
src/jobscout/pipeline/run.py           build_query(), run_ingest(), list_jobs()
src/jobscout/cli.py                    Typer app: fetch, jobs, serve
src/jobscout/api/__init__.py
src/jobscout/api/schemas.py            JobRead, PreferencesRead, PreferencesUpdate
src/jobscout/api/deps.py               get_session(), get_current_user()
src/jobscout/api/routers/jobs.py       GET /jobs
src/jobscout/api/routers/preferences.py GET/PUT /preferences
src/jobscout/api/app.py                create_app(), app, lifespan, GET /health
tests/conftest.py                      engine/session fixtures, fixture loader
tests/fixtures/arbeitnow_sample.json   3 real jobs, trimmed
tests/test_smoke.py
tests/test_config.py
tests/test_models.py
tests/sources/test_text.py
tests/sources/test_arbeitnow.py
tests/sources/test_registry.py
tests/sources/test_contract.py         generic test over every registered source
tests/pipeline/test_ingest.py
tests/pipeline/test_filters.py
tests/pipeline/test_users.py
tests/pipeline/test_run.py
tests/test_cli.py
tests/api/test_jobs.py
tests/api/test_preferences.py
tests/integration/test_arbeitnow_live.py  marked integration
```

---

### Task 1: Project skeleton with uv, ruff, pytest

**Files:**
- Create: `.python-version`, `.gitattributes`, `pyproject.toml`, `src/jobscout/__init__.py`, `tests/__init__.py`, `tests/test_smoke.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `jobscout.__version__: str`; the `uv run pytest` / `uv run ruff` toolchain every later task uses.

- [ ] **Step 1: Install uv and Python 3.12**

Run (PowerShell):
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
Then open a new shell (or use the full path `$env:USERPROFILE\.local\bin\uv.exe`) and run:
```powershell
uv --version
uv python install 3.12
```
Expected: `uv 0.x.y` printed; Python 3.12 installed.

- [ ] **Step 2: Create `.python-version` and `.gitattributes`**

`.python-version`:
```
3.12
```

`.gitattributes`:
```
* text=auto eol=lf
```

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[project]
name = "jobscout"
version = "0.1.0"
description = "Open-source AI agent that continuously finds tech jobs matching your profile."
readme = "README.md"
license = "MIT"
requires-python = ">=3.12"
authors = [{ name = "Filippo Turazzi" }]
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlmodel>=0.0.22",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "httpx>=0.27",
    "typer>=0.12",
]

[project.scripts]
jobscout = "jobscout.cli:app"

[dependency-groups]
dev = [
    "pytest>=8",
    "ruff>=0.6",
    "respx>=0.21",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/jobscout"]

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.ruff.format]
line-ending = "lf"

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "integration: hits real external services; deselected by default",
]
addopts = "-m 'not integration'"
```

- [ ] **Step 4: Create the package and the smoke test**

`src/jobscout/__init__.py`:
```python
"""JobScout: an open-source agent that continuously finds jobs matching your profile."""

__version__ = "0.1.0"
```

`tests/__init__.py`: empty file.

`tests/test_smoke.py`:
```python
import jobscout


def test_version_is_set():
    assert jobscout.__version__ == "0.1.0"
```

- [ ] **Step 5: Extend `.gitignore`**

Append to the existing `.gitignore`:
```
uv.lock.bak
*.egg-info/
.coverage
htmlcov/
```
(`.venv/`, `.env`, `*.db`, caches are already there.)

- [ ] **Step 6: Sync and run**

Run:
```powershell
uv sync --all-groups
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
```
Expected: `uv.lock` created; `1 passed`; ruff reports no issues. (If `ruff format --check` complains, run `uv run ruff format .` and re-check.)

- [ ] **Step 7: Commit**

```powershell
git add .python-version .gitattributes pyproject.toml uv.lock .gitignore src/jobscout/__init__.py tests/__init__.py tests/test_smoke.py
git commit -m "chore: bootstrap uv project with ruff and pytest" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: CI, license, README skeleton, .env.example

**Files:**
- Create: `.github/workflows/ci.yml`, `LICENSE`, `README.md`, `.env.example`

**Interfaces:**
- Produces: CI that runs `ruff check`, `ruff format --check`, `pytest` on every push/PR.

- [ ] **Step 1: Create the workflow**

`.github/workflows/ci.yml`:
```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv python install 3.12
      - run: uv sync --all-groups
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest
```

- [ ] **Step 2: Create `LICENSE`** (MIT, year 2026, holder "Filippo Turazzi")

```
MIT License

Copyright (c) 2026 Filippo Turazzi

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 3: Create `README.md`**

````markdown
# JobScout

Open-source AI agent that continuously searches public job-board APIs and matches
postings against **your** profile — with an LLM explaining every score.

> Status: early development. Stage 1 (collection, no AI yet) in progress.
> See `docs/superpowers/specs/2026-09-19-jobscout-design.md` for the full design and roadmap.

## Quick start

```bash
uv sync --all-groups
cp .env.example .env          # optional; defaults work out of the box
uv run jobscout fetch         # pull jobs from Arbeitnow into ./jobscout.db
uv run jobscout jobs          # list jobs that pass your preferences
uv run jobscout serve         # API at http://127.0.0.1:8000/docs
```

## Development

```bash
uv run pytest                 # unit tests (no network)
uv run pytest -m integration  # hits real APIs; opt-in
uv run ruff check . && uv run ruff format .
```

## Job sources

- [Arbeitnow](https://www.arbeitnow.com) — free public API, Europe/remote focus.

## License

MIT
````

- [ ] **Step 4: Create `.env.example`**

```
# Operator configuration. Copy to .env. All variables are optional.

# SQLAlchemy URL. Default is a local SQLite file. Use postgresql+psycopg://... for Postgres.
DATABASE_URL=sqlite:///./jobscout.db

# Comma-separated list of enabled job sources.
SOURCES=arbeitnow

# How many pages (250 jobs each) to pull from Arbeitnow per fetch. Be gentle with the free API.
ARBEITNOW_MAX_PAGES=2

# Jobs not seen in any fetch for this many days are marked inactive (used from stage 3).
INACTIVE_AFTER_DAYS=14

# When preferences change, re-match jobs first seen within this window (used from stage 2).
BACKFILL_WINDOW_DAYS=30
```

- [ ] **Step 5: Verify locally and commit**

Run: `uv run ruff check . ; uv run pytest -q`
Expected: no lint errors, `1 passed`.

```powershell
git add .github/workflows/ci.yml LICENSE README.md .env.example
git commit -m "ci: add GitHub Actions workflow, MIT license, README and .env.example" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Settings

**Files:**
- Create: `src/jobscout/config.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `class Settings(BaseSettings)` with fields `database_url: str`, `sources: str`, `arbeitnow_max_pages: int`, `inactive_after_days: int`, `backfill_window_days: int`, `api_host: str`, `api_port: int`, and property `source_names -> list[str]`.
  - `get_settings() -> Settings` (cached).

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
from jobscout.config import Settings, get_settings


def test_defaults_work_without_env():
    s = Settings(_env_file=None)
    assert s.database_url == "sqlite:///./jobscout.db"
    assert s.source_names == ["arbeitnow"]
    assert s.arbeitnow_max_pages == 2
    assert s.inactive_after_days == 14
    assert s.backfill_window_days == 30


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("SOURCES", "arbeitnow, remoteok ,")
    monkeypatch.setenv("ARBEITNOW_MAX_PAGES", "5")
    s = Settings(_env_file=None)
    assert s.database_url == "sqlite://"
    assert s.source_names == ["arbeitnow", "remoteok"]
    assert s.arbeitnow_max_pages == 5


def test_get_settings_is_cached():
    get_settings.cache_clear()
    assert get_settings() is get_settings()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.config'`

- [ ] **Step 3: Implement**

`src/jobscout/config.py`:
```python
"""Operator configuration, read from environment variables or a .env file.

Anything that describes *who runs this instance* (database, enabled sources, intervals,
provider keys) belongs here. Anything that describes *what a user wants* belongs in
``UserPreferences`` — never here.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./jobscout.db"
    sources: str = "arbeitnow"
    arbeitnow_max_pages: int = 2
    inactive_after_days: int = 14
    backfill_window_days: int = 30
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    @property
    def source_names(self) -> list[str]:
        return [name.strip() for name in self.sources.split(",") if name.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: 3 passed.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/config.py tests/test_config.py
git commit -m "feat: add operator Settings from env" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Models and database

**Files:**
- Create: `src/jobscout/models/__init__.py`, `src/jobscout/models/base.py`, `src/jobscout/models/user.py`, `src/jobscout/models/job.py`, `src/jobscout/db.py`, `tests/conftest.py`, `tests/test_models.py`

**Interfaces:**
- Produces:
  - `jobscout.models.base.utcnow() -> datetime` (naive UTC).
  - Tables `User`, `UserPreferences`, `Job` (fields below).
  - `jobscout.db.create_engine_from_url(url: str) -> Engine`, `init_db(engine) -> None`, `get_engine() -> Engine` (cached, from `get_settings().database_url`).
  - Test fixtures `engine`, `session`, `load_fixture(name) -> dict`.

- [ ] **Step 1: Write the failing tests**

`tests/conftest.py`:
```python
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session

from jobscout.db import create_engine_from_url, init_db

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def engine():
    engine = create_engine_from_url("sqlite://")
    init_db(engine)
    return engine


@pytest.fixture
def session(engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))
```

`tests/test_models.py`:
```python
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from jobscout.models import Job, User, UserPreferences
from jobscout.models.base import utcnow


def test_utcnow_is_naive():
    now = utcnow()
    assert isinstance(now, datetime)
    assert now.tzinfo is None


def _job(**overrides) -> Job:
    data = dict(
        source="arbeitnow",
        external_id="abc-1",
        title="AI Engineer",
        company="Acme",
        location="Berlin",
        remote=True,
        url="https://example.com/abc-1",
        description="Build things.",
        tags=["python", "llm"],
        content_hash="h1",
        raw={"slug": "abc-1"},
    )
    data.update(overrides)
    return Job(**data)


def test_job_roundtrip_with_json_columns(session):
    session.add(_job())
    session.commit()
    job = session.exec(select(Job)).one()
    assert job.tags == ["python", "llm"]
    assert job.raw == {"slug": "abc-1"}
    assert job.is_active is True
    assert job.first_seen_at.tzinfo is None
    assert job.embedding is None


def test_job_source_external_id_is_unique(session):
    session.add(_job())
    session.commit()
    session.add(_job(title="Duplicate"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_user_preferences_one_to_one(session):
    user = User(email="me@localhost")
    session.add(user)
    session.commit()
    session.add(UserPreferences(user_id=user.id, titles=["AI Engineer"]))
    session.commit()
    prefs = session.exec(select(UserPreferences)).one()
    assert prefs.titles == ["AI Engineer"]
    assert prefs.min_score_to_notify == 70
    assert prefs.work_modes == []
    session.add(UserPreferences(user_id=user.id))
    with pytest.raises(IntegrityError):
        session.commit()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.db'`

- [ ] **Step 3: Implement models**

`src/jobscout/models/base.py`:
```python
"""Shared model helpers.

All timestamps are naive UTC. SQLite discards tzinfo on read, so storing aware datetimes
would make comparisons between fresh and loaded values fail. Use ``utcnow()`` everywhere.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
```

`src/jobscout/models/user.py`:
```python
from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from jobscout.models.base import utcnow


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    locale: str = Field(default="en")
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=utcnow, nullable=False, sa_column_kwargs={"onupdate": utcnow}
    )


class UserPreferences(SQLModel, table=True):
    """What one user is looking for. Source of truth for filtering and (later) matching."""

    __tablename__ = "user_preferences"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", unique=True, index=True)
    titles: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    seniority: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    work_modes: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    regions: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    min_salary: int | None = None
    salary_currency: str | None = None
    required_skills: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    nice_to_have_skills: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    excluded_keywords: list[str] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    profile_summary: str = Field(default="")
    profile_embedding: bytes | None = None
    min_score_to_notify: int = Field(default=70)
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=utcnow, nullable=False, sa_column_kwargs={"onupdate": utcnow}
    )
```

`src/jobscout/models/job.py`:
```python
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from jobscout.models.base import utcnow


class Job(SQLModel, table=True):
    """A posting as seen on a source. Global: shared by all users."""

    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_job_source_external_id"),)

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    external_id: str = Field(index=True)
    title: str
    company: str
    location: str | None = None
    remote: bool = Field(default=False)
    url: str
    description: str
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    posted_at: datetime | None = None
    first_seen_at: datetime = Field(default_factory=utcnow, nullable=False)
    last_seen_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
    is_active: bool = Field(default=True, index=True)
    content_hash: str
    embedding: bytes | None = None
    raw: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=utcnow, nullable=False, sa_column_kwargs={"onupdate": utcnow}
    )
```

`src/jobscout/models/__init__.py`:
```python
from jobscout.models.job import Job
from jobscout.models.user import User, UserPreferences

__all__ = ["Job", "User", "UserPreferences"]
```

- [ ] **Step 4: Implement `db.py`**

`src/jobscout/db.py`:
```python
"""Engine and session helpers. SQLite by default; any SQLAlchemy URL via DATABASE_URL."""

from functools import lru_cache

from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from jobscout import models  # noqa: F401  (registers tables on SQLModel.metadata)
from jobscout.config import get_settings


def create_engine_from_url(url: str) -> Engine:
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            # One shared in-memory database across connections (tests).
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url)


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)


@lru_cache
def get_engine() -> Engine:
    return create_engine_from_url(get_settings().database_url)
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: 4 passed.

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/models src/jobscout/db.py tests/conftest.py tests/test_models.py
git commit -m "feat: add User, UserPreferences, Job models and SQLite engine helpers" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Source contracts and HTML-to-text helper

**Files:**
- Create: `src/jobscout/sources/__init__.py`, `src/jobscout/sources/base.py`, `src/jobscout/sources/text.py`, `tests/sources/__init__.py`, `tests/sources/test_text.py`

**Interfaces:**
- Produces:
  - `RawJob(BaseModel)`: `source: str, external_id: str, title: str, company: str, location: str | None, remote: bool, url: str, description: str, salary_min: int | None, salary_max: int | None, salary_currency: str | None, tags: list[str], posted_at: datetime | None, raw: dict[str, Any]`.
  - `SearchQuery(BaseModel)`: `keywords: list[str] = [], remote_only: bool = False, locations: list[str] = []`.
  - `class JobSource(Protocol)`: `name: str`; `def fetch(self, query: SearchQuery) -> list[RawJob]`.
  - `html_to_text(value: str) -> str`.

Design note: the spec says `fetch(prefs)`. Sources must not import DB models, so `pipeline` converts `UserPreferences` into this small `SearchQuery` (Task 11, `build_query`). Arbeitnow has no server-side filters, so it only honors `remote_only` client-side; sources with search APIs (Adzuna, stage 5) will use `keywords`/`locations`.

- [ ] **Step 1: Write the failing tests**

`tests/sources/__init__.py`: empty.

`tests/sources/test_text.py`:
```python
from jobscout.sources.text import html_to_text


def test_strips_tags_and_collapses_whitespace():
    html = "<p>Hello <strong>world</strong></p>\n\n<ul><li>one</li><li>two</li></ul>"
    assert html_to_text(html) == "Hello world one two"


def test_handles_html_escaped_html():
    escaped = "&lt;div class=&quot;x&quot;&gt;&lt;h2&gt;Brief&amp;nbsp;info&lt;/h2&gt;&lt;/div&gt;"
    assert html_to_text(escaped) == "Brief info"


def test_plain_text_unchanged():
    assert html_to_text("Just text.") == "Just text."


def test_empty():
    assert html_to_text("") == ""
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/sources/test_text.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.sources'`

- [ ] **Step 3: Implement**

`src/jobscout/sources/__init__.py`:
```python
from jobscout.sources.base import JobSource, RawJob, SearchQuery

__all__ = ["JobSource", "RawJob", "SearchQuery"]
```

`src/jobscout/sources/text.py`:
```python
"""Turn job-board HTML (sometimes HTML-escaped HTML) into plain text."""

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def html_to_text(value: str) -> str:
    if not value:
        return ""
    # Some boards double-encode: "&lt;p&gt;" instead of "<p>". Unescape first so tags
    # become real tags, strip them, then unescape again for entities inside the text.
    text = html.unescape(value)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    return _WS_RE.sub(" ", text).strip()
```

`src/jobscout/sources/base.py`:
```python
"""Contracts every job source implements. Sources know nothing about the database."""

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class SearchQuery(BaseModel):
    """What the pipeline asks a source for, derived from user preferences."""

    keywords: list[str] = Field(default_factory=list)
    remote_only: bool = False
    locations: list[str] = Field(default_factory=list)


class RawJob(BaseModel):
    """A normalized posting as returned by a source, before persistence."""

    source: str
    external_id: str
    title: str
    company: str
    location: str | None = None
    remote: bool = False
    url: str
    description: str
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    tags: list[str] = Field(default_factory=list)
    posted_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class JobSource(Protocol):
    name: str

    def fetch(self, query: SearchQuery) -> list[RawJob]: ...
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/sources/test_text.py -v`
Expected: 4 passed.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/sources tests/sources
git commit -m "feat: add RawJob, SearchQuery, JobSource protocol and html_to_text" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: ArbeitnowSource

**Files:**
- Create: `src/jobscout/sources/arbeitnow.py`, `tests/fixtures/arbeitnow_sample.json`, `tests/sources/test_arbeitnow.py`

**Interfaces:**
- Consumes: `RawJob`, `SearchQuery`, `html_to_text` (Task 5).
- Produces: `ArbeitnowSource(client: httpx.Client | None = None, max_pages: int = 2)` with `name = "arbeitnow"` and `fetch(query) -> list[RawJob]`; module constant `BASE_URL = "https://www.arbeitnow.com/api/job-board-api"`.

Real API shape (verified 2026-09-19): `{"data": [...], "links": {"next": url|null, ...}, "meta": {...}}`; each item has `slug, company_name, title, description (HTML, sometimes HTML-escaped), remote (bool), url, tags (list), job_types (list), location (str), created_at (unix seconds)`. No salary. 250 items per page; paginate with `?page=N`.

- [ ] **Step 1: Create the fixture**

`tests/fixtures/arbeitnow_sample.json` (real records, descriptions trimmed, tag lists shortened):
```json
{
  "data": [
    {
      "slug": "remote-ai-developer-nurnberg-177325",
      "company_name": "Partspace",
      "title": "AI Developer (m/f/d)",
      "description": "<br><strong>Join the AI of Manufacturing</strong><p><span style=\"font-family:Arial;\">PartSpace builds Document AI for CAD/CAM.</span></p>",
      "remote": true,
      "url": "https://www.arbeitnow.com/jobs/companies/partspace/remote-ai-developer-nurnberg-177325",
      "tags": ["C#", ".NET", "LLMs", "MLOps", "Computer Vision", "remote"],
      "job_types": ["Experienced", "Permanent", "Full time"],
      "location": "Nürnberg",
      "created_at": 1789848555
    },
    {
      "slug": "senior-decision-scientist-trust-safety-berlin-349233",
      "company_name": "Vinteden",
      "title": "Senior Decision Scientist, Trust & Safety",
      "description": "&lt;div class=&quot;content-intro&quot;&gt;&lt;h2&gt;&lt;strong&gt;Brief info about Vinted&amp;nbsp;&lt;/strong&gt;&lt;/h2&gt;\n&lt;p&gt;Our marketplace.&lt;/p&gt;",
      "remote": false,
      "url": "https://www.arbeitnow.com/jobs/companies/vinteden/senior-decision-scientist-trust-safety-berlin-349233",
      "tags": ["Data Science & Analytics"],
      "job_types": [],
      "location": "Berlin",
      "created_at": 1789851317
    },
    {
      "slug": "ai-application-engineer-ai-products-llm-rag-berlin-232153",
      "company_name": "Machine Learning Reply",
      "title": "AI Application Engineer – AI Products (LLM & RAG) (m/f/d)",
      "description": "<p>At Machine Learning Reply, we help organizations turn cutting-edge AI technologies into real-world applications.</p><p style=\"min-height: 1.7em;\"></p><p>To strengthen our team, we are looking for you.</p>",
      "remote": false,
      "url": "https://www.arbeitnow.com/jobs/companies/machine-learning-reply/ai-application-engineer-ai-products-llm-rag-berlin-232153",
      "tags": ["Machine Learning Engineering"],
      "job_types": ["Mid", "fulltime permanent"],
      "location": "Berlin, Berlin, Germany",
      "created_at": 1789849840
    }
  ],
  "links": {
    "first": "https://www.arbeitnow.com/api/job-board-api?page=1",
    "last": null,
    "prev": null,
    "next": null
  },
  "meta": {
    "current_page": 1,
    "per_page": 250,
    "from": 1,
    "to": 3,
    "path": "https://www.arbeitnow.com/api/job-board-api",
    "current_page_url": "https://www.arbeitnow.com/api/job-board-api?page=1"
  }
}
```

- [ ] **Step 2: Write the failing tests**

`tests/sources/test_arbeitnow.py`:
```python
import copy
from datetime import datetime

import httpx
import pytest
import respx

from jobscout.sources.arbeitnow import BASE_URL, ArbeitnowSource
from jobscout.sources.base import RawJob, SearchQuery
from tests.conftest import load_fixture


@pytest.fixture
def sample():
    return load_fixture("arbeitnow_sample.json")


@respx.mock
def test_fetch_maps_fields(sample):
    respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(200, json=sample))
    jobs = ArbeitnowSource(max_pages=1).fetch(SearchQuery())

    assert len(jobs) == 3
    assert all(isinstance(j, RawJob) for j in jobs)
    first = jobs[0]
    assert first.source == "arbeitnow"
    assert first.external_id == "remote-ai-developer-nurnberg-177325"
    assert first.title == "AI Developer (m/f/d)"
    assert first.company == "Partspace"
    assert first.location == "Nürnberg"
    assert first.remote is True
    assert first.url.endswith("/remote-ai-developer-nurnberg-177325")
    assert first.description == (
        "Join the AI of Manufacturing PartSpace builds Document AI for CAD/CAM."
    )
    assert "LLMs" in first.tags
    assert first.posted_at == datetime(2026, 9, 19, 20, 9, 15)
    assert first.raw["slug"] == first.external_id


@respx.mock
def test_fetch_decodes_escaped_html(sample):
    respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(200, json=sample))
    jobs = ArbeitnowSource(max_pages=1).fetch(SearchQuery())
    assert jobs[1].description == "Brief info about Vinted Our marketplace."


@respx.mock
def test_fetch_follows_pages_up_to_max(sample):
    page1 = copy.deepcopy(sample)
    page1["links"]["next"] = f"{BASE_URL}?page=2"
    page2 = copy.deepcopy(sample)
    page2["data"] = [dict(sample["data"][0], slug="another-slug-1")]
    page2["links"]["next"] = f"{BASE_URL}?page=3"
    r1 = respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(200, json=page1))
    r2 = respx.get(BASE_URL, params={"page": 2}).mock(return_value=httpx.Response(200, json=page2))
    r3 = respx.get(BASE_URL, params={"page": 3}).mock(return_value=httpx.Response(200, json=sample))

    jobs = ArbeitnowSource(max_pages=2).fetch(SearchQuery())

    assert r1.called and r2.called and not r3.called
    assert [j.external_id for j in jobs][-1] == "another-slug-1"
    assert len(jobs) == 4


@respx.mock
def test_fetch_stops_when_no_next_link(sample):
    r1 = respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(200, json=sample))
    r2 = respx.get(BASE_URL, params={"page": 2}).mock(return_value=httpx.Response(200, json=sample))
    ArbeitnowSource(max_pages=5).fetch(SearchQuery())
    assert r1.called and not r2.called


@respx.mock
def test_remote_only_filters_client_side(sample):
    respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(200, json=sample))
    jobs = ArbeitnowSource(max_pages=1).fetch(SearchQuery(remote_only=True))
    assert [j.external_id for j in jobs] == ["remote-ai-developer-nurnberg-177325"]


@respx.mock
def test_http_error_raises(sample):
    respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        ArbeitnowSource(max_pages=1).fetch(SearchQuery())


@respx.mock
def test_sends_user_agent(sample):
    route = respx.get(BASE_URL, params={"page": 1}).mock(
        return_value=httpx.Response(200, json=sample)
    )
    ArbeitnowSource(max_pages=1).fetch(SearchQuery())
    assert "jobscout" in route.calls.last.request.headers["user-agent"].lower()
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/sources/test_arbeitnow.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.sources.arbeitnow'`

- [ ] **Step 4: Implement**

`src/jobscout/sources/arbeitnow.py`:
```python
"""Arbeitnow job board (https://www.arbeitnow.com). Free public API, no key.

Terms (from the API's own ``meta.terms``): do not abuse; link back to arbeitnow.com.
Jobs are ordered by ``created_at`` desc and paginated with ``?page=N`` (250 per page).
"""

from datetime import UTC, datetime
from typing import Any

import httpx

from jobscout import __version__
from jobscout.sources.base import RawJob, SearchQuery
from jobscout.sources.text import html_to_text

BASE_URL = "https://www.arbeitnow.com/api/job-board-api"
USER_AGENT = f"jobscout/{__version__} (+https://github.com/filippoturazzi/jobscout)"


class ArbeitnowSource:
    name = "arbeitnow"

    def __init__(self, client: httpx.Client | None = None, max_pages: int = 2) -> None:
        self._client = client or httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT})
        self._max_pages = max_pages

    def fetch(self, query: SearchQuery) -> list[RawJob]:
        jobs: list[RawJob] = []
        page = 1
        while page <= self._max_pages:
            response = self._client.get(BASE_URL, params={"page": page})
            response.raise_for_status()
            payload = response.json()
            jobs.extend(self._to_raw(item) for item in payload.get("data", []))
            if not payload.get("links", {}).get("next"):
                break
            page += 1
        if query.remote_only:
            jobs = [job for job in jobs if job.remote]
        return jobs

    @staticmethod
    def _to_raw(item: dict[str, Any]) -> RawJob:
        created = item.get("created_at")
        posted_at = (
            datetime.fromtimestamp(created, tz=UTC).replace(tzinfo=None) if created else None
        )
        return RawJob(
            source="arbeitnow",
            external_id=item["slug"],
            title=item["title"],
            company=item.get("company_name") or "",
            location=item.get("location") or None,
            remote=bool(item.get("remote", False)),
            url=item["url"],
            description=html_to_text(item.get("description", "")),
            tags=list(item.get("tags") or []) + list(item.get("job_types") or []),
            posted_at=posted_at,
            raw=item,
        )
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/sources/test_arbeitnow.py -v`
Expected: 7 passed. If `test_fetch_maps_fields` fails on `posted_at`, compute the expected value with `python -c "from datetime import datetime,UTC;print(datetime.fromtimestamp(1789848555,tz=UTC))"` and fix the **test's** literal — the implementation must stay UTC.

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/sources/arbeitnow.py tests/fixtures/arbeitnow_sample.json tests/sources/test_arbeitnow.py
git commit -m "feat: add ArbeitnowSource with pagination and fixture-based tests" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Source registry and generic contract test

**Files:**
- Create: `src/jobscout/sources/registry.py`, `tests/sources/test_registry.py`, `tests/sources/test_contract.py`

**Interfaces:**
- Consumes: `Settings` (Task 3), `ArbeitnowSource` (Task 6).
- Produces: `SOURCE_FACTORIES: dict[str, Callable[[Settings], JobSource]]`, `build_sources(settings: Settings) -> list[JobSource]` (raises `ValueError` naming unknown sources).

- [ ] **Step 1: Write the failing tests**

`tests/sources/test_registry.py`:
```python
import pytest

from jobscout.config import Settings
from jobscout.sources.arbeitnow import ArbeitnowSource
from jobscout.sources.registry import SOURCE_FACTORIES, build_sources


def test_default_settings_build_arbeitnow():
    sources = build_sources(Settings(_env_file=None))
    assert len(sources) == 1
    assert isinstance(sources[0], ArbeitnowSource)
    assert sources[0].name == "arbeitnow"


def test_unknown_source_raises():
    with pytest.raises(ValueError, match="nope"):
        build_sources(Settings(_env_file=None, sources="arbeitnow,nope"))


def test_every_factory_name_matches_source_name():
    settings = Settings(_env_file=None)
    for name, factory in SOURCE_FACTORIES.items():
        assert factory(settings).name == name
```

`tests/sources/test_contract.py`:
```python
"""Generic contract every registered source must satisfy.

Each source registers a fixture file ``tests/fixtures/<name>_sample.json`` and the URL
it hits; the test mocks that URL and checks the RawJob invariants. Adding a source means
adding one entry to ``SOURCE_HTTP_FIXTURES`` here.
"""

import httpx
import pytest
import respx

from jobscout.config import Settings
from jobscout.sources.arbeitnow import BASE_URL as ARBEITNOW_URL
from jobscout.sources.base import JobSource, RawJob, SearchQuery
from jobscout.sources.registry import SOURCE_FACTORIES
from tests.conftest import load_fixture

SOURCE_HTTP_FIXTURES: dict[str, tuple[str, str]] = {
    "arbeitnow": (ARBEITNOW_URL, "arbeitnow_sample.json"),
}


@pytest.mark.parametrize("name", sorted(SOURCE_FACTORIES))
@respx.mock
def test_source_contract(name):
    assert name in SOURCE_HTTP_FIXTURES, f"register a fixture for source {name!r}"
    url, fixture = SOURCE_HTTP_FIXTURES[name]
    respx.get(url__startswith=url).mock(
        return_value=httpx.Response(200, json=load_fixture(fixture))
    )
    source = SOURCE_FACTORIES[name](Settings(_env_file=None))

    assert isinstance(source, JobSource)
    jobs = source.fetch(SearchQuery())

    assert jobs, "fixture must yield at least one job"
    ids = [j.external_id for j in jobs]
    assert len(ids) == len(set(ids)), "external_id must be unique within a fetch"
    for job in jobs:
        assert isinstance(job, RawJob)
        assert job.source == name
        assert job.external_id and job.title and job.url and job.description
        assert "<" not in job.description, "description must be plain text"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/sources/test_registry.py tests/sources/test_contract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.sources.registry'`

- [ ] **Step 3: Implement**

`src/jobscout/sources/registry.py`:
```python
"""Maps source names (as used in the SOURCES env var) to constructors."""

from collections.abc import Callable

from jobscout.config import Settings
from jobscout.sources.arbeitnow import ArbeitnowSource
from jobscout.sources.base import JobSource

SOURCE_FACTORIES: dict[str, Callable[[Settings], JobSource]] = {
    "arbeitnow": lambda settings: ArbeitnowSource(max_pages=settings.arbeitnow_max_pages),
}


def build_sources(settings: Settings) -> list[JobSource]:
    unknown = [name for name in settings.source_names if name not in SOURCE_FACTORIES]
    if unknown:
        raise ValueError(
            f"Unknown source(s) in SOURCES: {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(SOURCE_FACTORIES))}"
        )
    return [SOURCE_FACTORIES[name](settings) for name in settings.source_names]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/sources -v`
Expected: all pass (text 4, arbeitnow 7, registry 3, contract 1).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/sources/registry.py tests/sources/test_registry.py tests/sources/test_contract.py
git commit -m "feat: add source registry and generic source contract test" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Ingest — upsert with dedup, liveness and content hash

**Files:**
- Create: `src/jobscout/pipeline/__init__.py`, `src/jobscout/pipeline/ingest.py`, `tests/pipeline/__init__.py`, `tests/pipeline/test_ingest.py`

**Interfaces:**
- Consumes: `Job` (Task 4), `RawJob`, `SearchQuery`, `JobSource` (Task 5).
- Produces:
  - `content_hash(title: str, description: str) -> str`
  - `@dataclass UpsertStats(created: int, updated: int, changed: int)`
  - `upsert_jobs(session: Session, raw_jobs: list[RawJob], now: datetime | None = None) -> UpsertStats`
  - `@dataclass IngestResult(source: str, fetched: int, created: int, updated: int, changed: int, error: str | None)`
  - `ingest(session: Session, sources: list[JobSource], query: SearchQuery, now: datetime | None = None) -> list[IngestResult]`

Stage-2 note: when the hash changes, existing `Match` rows must be marked `stale`. `Match` does not exist yet; `upsert_jobs` clears `Job.embedding` now and stage 2 adds the `Match` update in the same branch.

- [ ] **Step 1: Write the failing tests**

`tests/pipeline/__init__.py`: empty.

`tests/pipeline/test_ingest.py`:
```python
from datetime import datetime, timedelta

from sqlmodel import select

from jobscout.models import Job
from jobscout.pipeline.ingest import content_hash, ingest, upsert_jobs
from jobscout.sources.base import RawJob, SearchQuery

T0 = datetime(2026, 9, 20, 12, 0, 0)


def raw(external_id="j1", title="AI Engineer", description="Build agents.", **kw) -> RawJob:
    data = dict(
        source="test",
        external_id=external_id,
        title=title,
        company="Acme",
        location="Berlin",
        remote=True,
        url=f"https://example.com/{external_id}",
        description=description,
        tags=["python"],
        raw={"id": external_id},
    )
    data.update(kw)
    return RawJob(**data)


def test_content_hash_is_stable_and_sensitive():
    assert content_hash("a", "b") == content_hash("a", "b")
    assert content_hash("a", "b") != content_hash("a", "c")
    assert len(content_hash("a", "b")) == 64


def test_insert_new_jobs(session):
    stats = upsert_jobs(session, [raw("j1"), raw("j2")], now=T0)
    assert (stats.created, stats.updated, stats.changed) == (2, 0, 0)
    jobs = session.exec(select(Job).order_by(Job.external_id)).all()
    assert [j.external_id for j in jobs] == ["j1", "j2"]
    j1 = jobs[0]
    assert j1.first_seen_at == T0 and j1.last_seen_at == T0
    assert j1.is_active is True
    assert j1.content_hash == content_hash("AI Engineer", "Build agents.")
    assert j1.raw == {"id": "j1"}


def test_rerun_same_data_only_touches_last_seen(session):
    upsert_jobs(session, [raw("j1")], now=T0)
    later = T0 + timedelta(hours=1)
    stats = upsert_jobs(session, [raw("j1")], now=later)
    assert (stats.created, stats.updated, stats.changed) == (0, 1, 0)
    j1 = session.exec(select(Job)).one()
    assert j1.first_seen_at == T0
    assert j1.last_seen_at == later
    assert session.exec(select(Job)).all().__len__() == 1


def test_changed_content_updates_text_and_clears_embedding(session):
    upsert_jobs(session, [raw("j1")], now=T0)
    j1 = session.exec(select(Job)).one()
    j1.embedding = b"\x00\x01"
    j1.is_active = False
    session.add(j1)
    session.commit()

    stats = upsert_jobs(session, [raw("j1", description="Build better agents.")], now=T0)
    assert (stats.created, stats.updated, stats.changed) == (0, 0, 1)
    session.refresh(j1)
    assert j1.description == "Build better agents."
    assert j1.embedding is None
    assert j1.content_hash == content_hash("AI Engineer", "Build better agents.")
    assert j1.is_active is True, "a job seen again is active again"


def test_seen_again_reactivates(session):
    upsert_jobs(session, [raw("j1")], now=T0)
    j1 = session.exec(select(Job)).one()
    j1.is_active = False
    session.add(j1)
    session.commit()
    upsert_jobs(session, [raw("j1")], now=T0 + timedelta(days=1))
    session.refresh(j1)
    assert j1.is_active is True


def test_duplicates_within_one_batch_are_collapsed(session):
    stats = upsert_jobs(session, [raw("j1"), raw("j1")], now=T0)
    assert stats.created == 1
    assert len(session.exec(select(Job)).all()) == 1


class FakeSource:
    def __init__(self, name, jobs=None, error=None):
        self.name = name
        self._jobs = jobs or []
        self._error = error

    def fetch(self, query: SearchQuery) -> list[RawJob]:
        if self._error:
            raise self._error
        return self._jobs


def test_ingest_isolates_source_failures(session):
    ok = FakeSource("ok", [raw("a", source="ok")])
    bad = FakeSource("bad", error=RuntimeError("boom"))
    results = ingest(session, [bad, ok], SearchQuery(), now=T0)

    assert [r.source for r in results] == ["bad", "ok"]
    assert results[0].error == "RuntimeError: boom"
    assert results[0].fetched == 0
    assert results[1].error is None
    assert (results[1].fetched, results[1].created) == (1, 1)
    assert len(session.exec(select(Job)).all()) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pipeline/test_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.pipeline'`

- [ ] **Step 3: Implement**

`src/jobscout/pipeline/__init__.py`: empty.

`src/jobscout/pipeline/ingest.py`:
```python
"""Fetch from sources and upsert into the ``job`` table.

Idempotent: re-running with the same data only advances ``last_seen_at``. A changed
title/description updates the text, clears the cached embedding (stage 2 also marks
matches stale) and keeps ``first_seen_at``.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime

from sqlmodel import Session, select

from jobscout.models import Job
from jobscout.models.base import utcnow
from jobscout.sources.base import JobSource, RawJob, SearchQuery

log = logging.getLogger(__name__)


def content_hash(title: str, description: str) -> str:
    return hashlib.sha256(f"{title}\n{description}".encode()).hexdigest()


@dataclass
class UpsertStats:
    created: int = 0
    updated: int = 0
    changed: int = 0


@dataclass
class IngestResult:
    source: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    changed: int = 0
    error: str | None = None


def upsert_jobs(
    session: Session, raw_jobs: list[RawJob], now: datetime | None = None
) -> UpsertStats:
    now = now or utcnow()
    stats = UpsertStats()
    # Collapse duplicates inside the batch; last one wins.
    by_key = {(r.source, r.external_id): r for r in raw_jobs}
    if not by_key:
        return stats

    sources = {k[0] for k in by_key}
    existing = {
        (j.source, j.external_id): j
        for j in session.exec(select(Job).where(Job.source.in_(sources))).all()
        if (j.source, j.external_id) in by_key
    }

    for key, raw in by_key.items():
        new_hash = content_hash(raw.title, raw.description)
        job = existing.get(key)
        if job is None:
            session.add(
                Job(
                    **raw.model_dump(),
                    content_hash=new_hash,
                    first_seen_at=now,
                    last_seen_at=now,
                    is_active=True,
                )
            )
            stats.created += 1
            continue

        job.last_seen_at = now
        job.is_active = True
        if job.content_hash != new_hash:
            for field, value in raw.model_dump(exclude={"source", "external_id"}).items():
                setattr(job, field, value)
            job.content_hash = new_hash
            job.embedding = None
            stats.changed += 1
        else:
            stats.updated += 1
        session.add(job)

    session.commit()
    return stats


def ingest(
    session: Session,
    sources: list[JobSource],
    query: SearchQuery,
    now: datetime | None = None,
) -> list[IngestResult]:
    """Fetch every source in isolation; one failing source never blocks the others."""
    results: list[IngestResult] = []
    for source in sources:
        result = IngestResult(source=source.name)
        try:
            raw_jobs = source.fetch(query)
        except Exception as exc:  # noqa: BLE001 - isolate any source failure
            log.exception("source %s failed", source.name)
            result.error = f"{type(exc).__name__}: {exc}"
            results.append(result)
            continue
        result.fetched = len(raw_jobs)
        stats = upsert_jobs(session, raw_jobs, now=now)
        result.created, result.updated, result.changed = (
            stats.created,
            stats.updated,
            stats.changed,
        )
        results.append(result)
    return results
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/pipeline/test_ingest.py -v`
Expected: 7 passed.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/pipeline tests/pipeline
git commit -m "feat: add ingest upsert with dedup, liveness tracking and content hash" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Deterministic preference filters

**Files:**
- Create: `src/jobscout/pipeline/filters.py`, `tests/pipeline/test_filters.py`

**Interfaces:**
- Consumes: `Job`, `UserPreferences` (Task 4).
- Produces: `job_matches_preferences(job: Job, prefs: UserPreferences) -> bool`, `filter_jobs(jobs: Iterable[Job], prefs: UserPreferences) -> list[Job]`.

Rules (coarse on purpose — the AI matching in stage 2 does the nuanced part):
1. **Excluded keywords**: any `excluded_keywords` entry found (case-insensitive) in title or tags → reject.
2. **Work mode**: empty `work_modes` → pass. Remote job passes iff `"remote"` in `work_modes`. Non-remote job passes iff `"hybrid"` or `"onsite"` in `work_modes`.
3. **Region**: empty `regions` or remote job → pass. Otherwise `job.location` must contain (case-insensitive) one of the regions.
4. **Titles**: empty `titles` → pass. Otherwise every word of at least one preferred title must appear among the job title's words (so "AI Engineer" matches "AI Application Engineer").

- [ ] **Step 1: Write the failing tests**

`tests/pipeline/test_filters.py`:
```python
from jobscout.models import Job, UserPreferences
from jobscout.pipeline.filters import filter_jobs, job_matches_preferences


def job(title="AI Engineer", location="Berlin, Germany", remote=False, tags=None) -> Job:
    return Job(
        source="t",
        external_id=title.lower(),
        title=title,
        company="Acme",
        location=location,
        remote=remote,
        url="https://x",
        description="",
        tags=tags or [],
        content_hash="h",
    )


def prefs(**kw) -> UserPreferences:
    return UserPreferences(user_id=1, **kw)


def test_empty_preferences_accept_everything():
    assert job_matches_preferences(job(), prefs())
    assert job_matches_preferences(job(remote=True, location=None), prefs())


def test_excluded_keywords_reject_by_title_or_tag():
    p = prefs(excluded_keywords=["senior", "PHP"])
    assert not job_matches_preferences(job(title="Senior AI Engineer"), p)
    assert not job_matches_preferences(job(tags=["php"]), p)
    assert job_matches_preferences(job(title="AI Engineer"), p)


def test_work_modes():
    assert job_matches_preferences(job(remote=True), prefs(work_modes=["remote"]))
    assert not job_matches_preferences(job(remote=False), prefs(work_modes=["remote"]))
    assert job_matches_preferences(job(remote=False), prefs(work_modes=["hybrid"]))
    assert job_matches_preferences(job(remote=False), prefs(work_modes=["onsite"]))
    assert not job_matches_preferences(job(remote=True), prefs(work_modes=["onsite"]))
    assert job_matches_preferences(job(remote=True), prefs(work_modes=["remote", "onsite"]))


def test_regions_apply_to_onsite_only():
    p = prefs(regions=["Germany", "Portugal"])
    assert job_matches_preferences(job(location="Berlin, Germany"), p)
    assert job_matches_preferences(job(location="lisbon, portugal"), p)
    assert not job_matches_preferences(job(location="Paris, France"), p)
    assert not job_matches_preferences(job(location=None), p)
    assert job_matches_preferences(job(location="Paris, France", remote=True), p)


def test_titles_match_by_word_subset():
    p = prefs(titles=["AI Engineer", "Machine Learning Engineer"])
    assert job_matches_preferences(job(title="AI Application Engineer (m/f/d)"), p)
    assert job_matches_preferences(job(title="Machine Learning Engineer"), p)
    assert not job_matches_preferences(job(title="Data Analyst"), p)
    assert not job_matches_preferences(job(title="AI Researcher"), p)


def test_filter_jobs_preserves_order():
    jobs = [job(title="Data Analyst"), job(title="AI Engineer"), job(title="AI Lead Engineer")]
    out = filter_jobs(jobs, prefs(titles=["AI Engineer"]))
    assert [j.title for j in out] == ["AI Engineer", "AI Lead Engineer"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pipeline/test_filters.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.pipeline.filters'`

- [ ] **Step 3: Implement**

`src/jobscout/pipeline/filters.py`:
```python
"""Cheap, deterministic pre-filter applied before (stage 2) semantic matching.

Coarse by design: its job is to drop obvious non-candidates, not to rank.
"""

import re
from collections.abc import Iterable

from jobscout.models import Job, UserPreferences

_WORD_RE = re.compile(r"[a-z0-9+#.]+")


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _passes_exclusions(job: Job, prefs: UserPreferences) -> bool:
    haystack = " ".join([job.title, *job.tags]).lower()
    return not any(kw.lower() in haystack for kw in prefs.excluded_keywords if kw.strip())


def _passes_work_mode(job: Job, prefs: UserPreferences) -> bool:
    modes = {m.lower() for m in prefs.work_modes}
    if not modes:
        return True
    if job.remote:
        return "remote" in modes
    return bool(modes & {"hybrid", "onsite"})


def _passes_region(job: Job, prefs: UserPreferences) -> bool:
    if not prefs.regions or job.remote:
        return True
    location = (job.location or "").lower()
    return any(region.lower() in location for region in prefs.regions if region.strip())


def _passes_titles(job: Job, prefs: UserPreferences) -> bool:
    if not prefs.titles:
        return True
    title_words = _words(job.title)
    return any(_words(t) and _words(t) <= title_words for t in prefs.titles)


def job_matches_preferences(job: Job, prefs: UserPreferences) -> bool:
    return (
        _passes_exclusions(job, prefs)
        and _passes_work_mode(job, prefs)
        and _passes_region(job, prefs)
        and _passes_titles(job, prefs)
    )


def filter_jobs(jobs: Iterable[Job], prefs: UserPreferences) -> list[Job]:
    return [job for job in jobs if job_matches_preferences(job, prefs)]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/pipeline/test_filters.py -v`
Expected: 6 passed.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/pipeline/filters.py tests/pipeline/test_filters.py
git commit -m "feat: add deterministic preference filters" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Default user and preferences service

**Files:**
- Create: `src/jobscout/pipeline/users.py`, `tests/pipeline/test_users.py`

**Interfaces:**
- Consumes: `User`, `UserPreferences` (Task 4).
- Produces:
  - `DEFAULT_USER_EMAIL = "me@localhost"`
  - `get_or_create_default_user(session: Session) -> User` (also guarantees a `UserPreferences` row exists)
  - `get_preferences(session: Session, user_id: int) -> UserPreferences`
  - `update_preferences(session: Session, user_id: int, changes: dict[str, Any]) -> UserPreferences`

- [ ] **Step 1: Write the failing tests**

`tests/pipeline/test_users.py`:
```python
import pytest
from sqlmodel import select

from jobscout.models import User, UserPreferences
from jobscout.pipeline.users import (
    DEFAULT_USER_EMAIL,
    get_or_create_default_user,
    get_preferences,
    update_preferences,
)


def test_creates_user_and_empty_preferences_once(session):
    user = get_or_create_default_user(session)
    again = get_or_create_default_user(session)
    assert user.id == again.id
    assert user.email == DEFAULT_USER_EMAIL
    assert len(session.exec(select(User)).all()) == 1
    prefs = session.exec(select(UserPreferences)).one()
    assert prefs.user_id == user.id
    assert prefs.titles == []


def test_get_preferences(session):
    user = get_or_create_default_user(session)
    assert get_preferences(session, user.id).user_id == user.id


def test_get_preferences_missing_user_raises(session):
    with pytest.raises(LookupError):
        get_preferences(session, 999)


def test_update_preferences_partial(session):
    user = get_or_create_default_user(session)
    prefs = update_preferences(
        session, user.id, {"titles": ["AI Engineer"], "work_modes": ["remote"]}
    )
    assert prefs.titles == ["AI Engineer"]
    assert prefs.work_modes == ["remote"]
    prefs = update_preferences(session, user.id, {"min_salary": 60000})
    assert prefs.titles == ["AI Engineer"], "untouched fields are kept"
    assert prefs.min_salary == 60000


def test_update_preferences_rejects_unknown_field(session):
    user = get_or_create_default_user(session)
    with pytest.raises(ValueError, match="nope"):
        update_preferences(session, user.id, {"nope": 1})
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pipeline/test_users.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.pipeline.users'`

- [ ] **Step 3: Implement**

`src/jobscout/pipeline/users.py`:
```python
"""Single fixed user until real auth arrives (stage 6). Everything is still keyed by user_id."""

from typing import Any

from sqlmodel import Session, select

from jobscout.models import User, UserPreferences

DEFAULT_USER_EMAIL = "me@localhost"

_PROTECTED_FIELDS = {"id", "user_id", "created_at", "updated_at", "profile_embedding"}


def get_or_create_default_user(session: Session) -> User:
    user = session.exec(select(User).where(User.email == DEFAULT_USER_EMAIL)).first()
    if user is None:
        user = User(email=DEFAULT_USER_EMAIL)
        session.add(user)
        session.commit()
        session.refresh(user)
    prefs = session.exec(
        select(UserPreferences).where(UserPreferences.user_id == user.id)
    ).first()
    if prefs is None:
        session.add(UserPreferences(user_id=user.id))
        session.commit()
    return user


def get_preferences(session: Session, user_id: int) -> UserPreferences:
    prefs = session.exec(select(UserPreferences).where(UserPreferences.user_id == user_id)).first()
    if prefs is None:
        raise LookupError(f"No preferences for user_id={user_id}")
    return prefs


def update_preferences(
    session: Session, user_id: int, changes: dict[str, Any]
) -> UserPreferences:
    allowed = set(UserPreferences.model_fields) - _PROTECTED_FIELDS
    unknown = set(changes) - allowed
    if unknown:
        raise ValueError(f"Unknown preference field(s): {', '.join(sorted(unknown))}")
    prefs = get_preferences(session, user_id)
    for field, value in changes.items():
        setattr(prefs, field, value)
    session.add(prefs)
    session.commit()
    session.refresh(prefs)
    return prefs
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/pipeline/test_users.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/pipeline/users.py tests/pipeline/test_users.py
git commit -m "feat: add default user bootstrap and preferences service" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Pipeline runner — `run_ingest` and `list_jobs`

**Files:**
- Create: `src/jobscout/pipeline/run.py`, `tests/pipeline/test_run.py`

**Interfaces:**
- Consumes: `ingest`, `IngestResult` (Task 8); `filter_jobs` (Task 9); `get_preferences` (Task 10); `build_sources` (Task 7); `Settings` (Task 3).
- Produces:
  - `build_query(prefs: UserPreferences) -> SearchQuery`
  - `run_ingest(session: Session, settings: Settings, user_id: int, sources: list[JobSource] | None = None) -> list[IngestResult]`
  - `list_jobs(session: Session, user_id: int, limit: int = 50, apply_filters: bool = True, active_only: bool = True) -> list[Job]` — newest first by `first_seen_at`.

- [ ] **Step 1: Write the failing tests**

`tests/pipeline/test_run.py`:
```python
from datetime import datetime, timedelta

from jobscout.config import Settings
from jobscout.models import UserPreferences
from jobscout.pipeline.ingest import upsert_jobs
from jobscout.pipeline.run import build_query, list_jobs, run_ingest
from jobscout.pipeline.users import get_or_create_default_user, update_preferences
from jobscout.sources.base import RawJob, SearchQuery

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
    )


class FakeSource:
    name = "fake"

    def __init__(self, jobs):
        self.jobs = jobs
        self.last_query = None

    def fetch(self, query: SearchQuery):
        self.last_query = query
        return self.jobs


def test_build_query_from_preferences():
    p = UserPreferences(user_id=1, titles=["AI Engineer"], work_modes=["remote"], regions=["DE"])
    q = build_query(p)
    assert q.keywords == ["AI Engineer"]
    assert q.remote_only is True
    assert q.locations == ["DE"]
    assert build_query(UserPreferences(user_id=1, work_modes=["remote", "hybrid"])).remote_only is False


def test_run_ingest_uses_prefs_and_given_sources(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"work_modes": ["remote"]})
    src = FakeSource([raw("a", "AI Engineer")])
    results = run_ingest(session, Settings(_env_file=None), user.id, sources=[src])
    assert src.last_query.remote_only is True
    assert results[0].created == 1


def test_list_jobs_filters_and_orders(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"titles": ["AI Engineer"]})
    upsert_jobs(session, [raw("old", "AI Engineer"), raw("x", "Data Analyst")], now=T0)
    upsert_jobs(session, [raw("new", "Senior AI Engineer")], now=T0 + timedelta(hours=1))

    jobs = list_jobs(session, user.id)
    assert [j.external_id for j in jobs] == ["new", "old"]

    everything = list_jobs(session, user.id, apply_filters=False)
    assert {j.external_id for j in everything} == {"old", "x", "new"}

    assert len(list_jobs(session, user.id, limit=1)) == 1


def test_list_jobs_hides_inactive_by_default(session):
    user = get_or_create_default_user(session)
    upsert_jobs(session, [raw("a", "AI Engineer")], now=T0)
    job = list_jobs(session, user.id)[0]
    job.is_active = False
    session.add(job)
    session.commit()
    assert list_jobs(session, user.id) == []
    assert len(list_jobs(session, user.id, active_only=False)) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pipeline/test_run.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.pipeline.run'`

- [ ] **Step 3: Implement**

`src/jobscout/pipeline/run.py`:
```python
"""Entry points used by the CLI and the API. The only place sources, DB and filters meet."""

from sqlmodel import Session, select

from jobscout.config import Settings
from jobscout.models import Job, UserPreferences
from jobscout.pipeline.filters import filter_jobs
from jobscout.pipeline.ingest import IngestResult, ingest
from jobscout.pipeline.users import get_preferences
from jobscout.sources.base import JobSource, SearchQuery
from jobscout.sources.registry import build_sources


def build_query(prefs: UserPreferences) -> SearchQuery:
    modes = {m.lower() for m in prefs.work_modes}
    return SearchQuery(
        keywords=list(prefs.titles),
        remote_only=modes == {"remote"},
        locations=list(prefs.regions),
    )


def run_ingest(
    session: Session,
    settings: Settings,
    user_id: int,
    sources: list[JobSource] | None = None,
) -> list[IngestResult]:
    prefs = get_preferences(session, user_id)
    sources = sources if sources is not None else build_sources(settings)
    return ingest(session, sources, build_query(prefs))


def list_jobs(
    session: Session,
    user_id: int,
    limit: int = 50,
    apply_filters: bool = True,
    active_only: bool = True,
) -> list[Job]:
    prefs = get_preferences(session, user_id)
    statement = select(Job).order_by(Job.first_seen_at.desc(), Job.id.desc())
    if active_only:
        statement = statement.where(Job.is_active.is_(True))
    jobs = list(session.exec(statement).all())
    if apply_filters:
        jobs = filter_jobs(jobs, prefs)
    return jobs[:limit]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/pipeline -v`
Expected: all pipeline tests pass.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/pipeline/run.py tests/pipeline/test_run.py
git commit -m "feat: add pipeline runner with run_ingest and list_jobs" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: Typer CLI — `fetch`, `jobs`, `serve`

**Files:**
- Create: `src/jobscout/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `get_settings` (Task 3); `create_engine_from_url`, `init_db` (Task 4); `run_ingest`, `list_jobs` (Task 11); `get_or_create_default_user` (Task 10).
- Produces: Typer `app` exposed as console script `jobscout` (already declared in `pyproject.toml`).

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ImportError: cannot import name 'cli'` (or ModuleNotFoundError).

- [ ] **Step 3: Implement**

`src/jobscout/cli.py`:
```python
"""Command-line interface. Thin shell over ``jobscout.pipeline``."""

from typing import Annotated

import typer
import uvicorn
from sqlmodel import Session

from jobscout.config import get_settings
from jobscout.db import create_engine_from_url, init_db
from jobscout.pipeline.run import list_jobs, run_ingest
from jobscout.pipeline.users import get_or_create_default_user

app = typer.Typer(help="JobScout: find jobs that match your profile.", no_args_is_help=True)


def _session() -> Session:
    engine = create_engine_from_url(get_settings().database_url)
    init_db(engine)
    return Session(engine)


@app.command()
def fetch() -> None:
    """Fetch jobs from all enabled sources into the database."""
    settings = get_settings()
    with _session() as session:
        user = get_or_create_default_user(session)
        results = run_ingest(session, settings, user.id)
    failed = False
    for r in results:
        if r.error:
            failed = True
            typer.echo(f"{r.source}: ERROR {r.error}")
        else:
            typer.echo(
                f"{r.source}: fetched={r.fetched} created={r.created} "
                f"updated={r.updated} changed={r.changed}"
            )
    if failed:
        raise typer.Exit(code=1)


@app.command()
def jobs(
    limit: Annotated[int, typer.Option(help="Max rows to show.")] = 20,
    all_jobs: Annotated[
        bool, typer.Option("--all", help="Ignore preferences; show every active job.")
    ] = False,
) -> None:
    """List active jobs that pass your preferences (newest first)."""
    with _session() as session:
        user = get_or_create_default_user(session)
        rows = list_jobs(session, user.id, limit=limit, apply_filters=not all_jobs)
        if not rows:
            typer.echo("No jobs found. Run `jobscout fetch` first or relax your preferences.")
            return
        for job in rows:
            mode = "remote" if job.remote else (job.location or "n/a")
            typer.echo(f"[{job.source}] {job.title} — {job.company} ({mode})\n    {job.url}")


@app.command()
def serve(
    host: Annotated[str | None, typer.Option()] = None,
    port: Annotated[int | None, typer.Option()] = None,
    reload: Annotated[bool, typer.Option(help="Auto-reload on code changes.")] = False,
) -> None:
    """Run the HTTP API (docs at /docs)."""
    settings = get_settings()
    uvicorn.run(
        "jobscout.api.app:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: 4 passed. (`test_serve_calls_uvicorn` does not import `jobscout.api.app`; it only checks the string.)

- [ ] **Step 5: Manual smoke against the real API**

Run: `uv run jobscout fetch` then `uv run jobscout jobs --all --limit 5`
Expected: `arbeitnow: fetched=500 created=500 ...` (numbers vary) and five real postings printed. A `jobscout.db` file appears in the repo root (gitignored).

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/cli.py tests/test_cli.py
git commit -m "feat: add CLI with fetch, jobs and serve commands" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: FastAPI — `/health`, `GET /jobs`, `GET/PUT /preferences`

**Files:**
- Create: `src/jobscout/api/__init__.py`, `src/jobscout/api/schemas.py`, `src/jobscout/api/deps.py`, `src/jobscout/api/routers/__init__.py`, `src/jobscout/api/routers/jobs.py`, `src/jobscout/api/routers/preferences.py`, `src/jobscout/api/app.py`, `tests/api/__init__.py`, `tests/api/conftest.py`, `tests/api/test_jobs.py`, `tests/api/test_preferences.py`

**Interfaces:**
- Consumes: `get_engine`, `init_db` (Task 4); `list_jobs` (Task 11); `get_or_create_default_user`, `get_preferences`, `update_preferences` (Task 10).
- Produces: ASGI `app` at `jobscout.api.app:app`; dependencies `get_session`, `get_current_user` in `jobscout.api.deps`.

- [ ] **Step 1: Write the failing tests**

`tests/api/__init__.py`: empty.

`tests/api/conftest.py`:
```python
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from jobscout.api.app import app
from jobscout.api.deps import get_session


@pytest.fixture
def client(engine) -> Iterator[TestClient]:
    def _override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _override
    # No `with` block on purpose: skipping the lifespan keeps the real engine out of tests.
    yield TestClient(app)
    app.dependency_overrides.clear()
```

`tests/api/test_jobs.py`:
```python
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
```

`tests/api/test_preferences.py`:
```python
def test_get_preferences_bootstraps_default_user(client):
    r = client.get("/preferences")
    assert r.status_code == 200
    body = r.json()
    assert body["titles"] == []
    assert body["min_score_to_notify"] == 70
    assert "profile_embedding" not in body


def test_put_preferences_partial_update(client):
    r = client.put("/preferences", json={"titles": ["AI Engineer"], "work_modes": ["remote"]})
    assert r.status_code == 200
    assert r.json()["titles"] == ["AI Engineer"]

    r = client.put("/preferences", json={"min_salary": 60000})
    assert r.status_code == 200
    assert r.json()["titles"] == ["AI Engineer"]
    assert r.json()["min_salary"] == 60000


def test_put_preferences_validates_work_mode(client):
    r = client.put("/preferences", json={"work_modes": ["on-the-moon"]})
    assert r.status_code == 422


def test_put_preferences_rejects_unknown_field(client):
    r = client.put("/preferences", json={"favorite_color": "blue"})
    assert r.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/api -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.api'`

- [ ] **Step 3: Implement schemas and deps**

`src/jobscout/api/__init__.py`: empty.
`src/jobscout/api/routers/__init__.py`: empty.

`src/jobscout/api/schemas.py`:
```python
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

WorkMode = Literal["remote", "hybrid", "onsite"]


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    external_id: str
    title: str
    company: str
    location: str | None
    remote: bool
    url: str
    description: str
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    tags: list[str]
    posted_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool


class PreferencesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    titles: list[str]
    seniority: list[str]
    work_modes: list[str]
    regions: list[str]
    min_salary: int | None
    salary_currency: str | None
    required_skills: list[str]
    nice_to_have_skills: list[str]
    excluded_keywords: list[str]
    profile_summary: str
    min_score_to_notify: int
    updated_at: datetime


class PreferencesUpdate(BaseModel):
    """All fields optional; only the ones sent are changed."""

    model_config = ConfigDict(extra="forbid")

    titles: list[str] | None = None
    seniority: list[str] | None = None
    work_modes: list[WorkMode] | None = None
    regions: list[str] | None = None
    min_salary: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    required_skills: list[str] | None = None
    nice_to_have_skills: list[str] | None = None
    excluded_keywords: list[str] | None = None
    profile_summary: str | None = None
    min_score_to_notify: int | None = Field(default=None, ge=0, le=100)
```

`src/jobscout/api/deps.py`:
```python
"""FastAPI dependencies. ``get_current_user`` is the single seam auth will replace in stage 6."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session

from jobscout.db import get_engine
from jobscout.models import User
from jobscout.pipeline.users import get_or_create_default_user


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def get_current_user(session: Annotated[Session, Depends(get_session)]) -> User:
    return get_or_create_default_user(session)
```

- [ ] **Step 4: Implement routers and app**

`src/jobscout/api/routers/jobs.py`:
```python
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from jobscout.api.deps import get_current_user, get_session
from jobscout.api.schemas import JobRead
from jobscout.models import User
from jobscout.pipeline.run import list_jobs

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobRead])
def read_jobs(
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    all: Annotated[bool, Query(description="Ignore preferences; return every active job.")] = False,
) -> list[JobRead]:
    jobs = list_jobs(session, user.id, limit=limit, apply_filters=not all)
    return [JobRead.model_validate(j) for j in jobs]
```

`src/jobscout/api/routers/preferences.py`:
```python
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from jobscout.api.deps import get_current_user, get_session
from jobscout.api.schemas import PreferencesRead, PreferencesUpdate
from jobscout.models import User
from jobscout.pipeline.users import get_preferences, update_preferences

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=PreferencesRead)
def read_preferences(
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> PreferencesRead:
    return PreferencesRead.model_validate(get_preferences(session, user.id))


@router.put("", response_model=PreferencesRead)
def put_preferences(
    payload: PreferencesUpdate,
    session: Annotated[Session, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
) -> PreferencesRead:
    changes = payload.model_dump(exclude_unset=True)
    return PreferencesRead.model_validate(update_preferences(session, user.id, changes))
```

`src/jobscout/api/app.py`:
```python
"""ASGI application. Run with ``jobscout serve`` or ``uvicorn jobscout.api.app:app``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import Session

from jobscout import __version__
from jobscout.api.routers import jobs, preferences
from jobscout.db import get_engine, init_db
from jobscout.pipeline.users import get_or_create_default_user


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    init_db(engine)
    with Session(engine) as session:
        get_or_create_default_user(session)
    yield


def create_app() -> FastAPI:
    application = FastAPI(title="JobScout", version=__version__, lifespan=lifespan)
    application.include_router(jobs.router)
    application.include_router(preferences.router)

    @application.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/api -v`
Expected: 8 passed.

- [ ] **Step 6: Manual check**

Run: `uv run jobscout serve` and open http://127.0.0.1:8000/docs. Call `GET /jobs?all=true&limit=3` — real jobs from Task 12's fetch appear. `PUT /preferences` with `{"titles": ["AI Engineer"], "work_modes": ["remote"]}` then `GET /jobs` — filtered list. Stop the server.

- [ ] **Step 7: Lint, run the full suite and commit**

Run: `uv run ruff check . ; uv run ruff format . ; uv run pytest -q`
Expected: all tests pass.
```powershell
git add src/jobscout/api tests/api
git commit -m "feat: add FastAPI app with /health, /jobs and /preferences" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 14: Integration test, docs and CLAUDE.md commands

**Files:**
- Create: `tests/integration/__init__.py`, `tests/integration/test_arbeitnow_live.py`
- Modify: `README.md`, `CLAUDE.md` (Commands and Current state sections)

**Interfaces:**
- Consumes: `ArbeitnowSource` (Task 6).

- [ ] **Step 1: Write the opt-in live test**

`tests/integration/__init__.py`: empty.

`tests/integration/test_arbeitnow_live.py`:
```python
"""Hits the real Arbeitnow API. Run explicitly: ``uv run pytest -m integration``."""

import pytest

from jobscout.sources.arbeitnow import ArbeitnowSource
from jobscout.sources.base import SearchQuery

pytestmark = pytest.mark.integration


def test_live_fetch_returns_well_formed_jobs():
    jobs = ArbeitnowSource(max_pages=1).fetch(SearchQuery())
    assert len(jobs) > 50
    first = jobs[0]
    assert first.external_id and first.title and first.url.startswith("https://")
    assert "<" not in first.description
```

- [ ] **Step 2: Verify default run skips it and explicit run executes it**

Run: `uv run pytest -q`
Expected: the live test is **not** collected/run (count unchanged, "deselected" in summary).

Run: `uv run pytest -m integration -v`
Expected: `1 passed` (requires internet).

- [ ] **Step 3: Update `README.md`**

Replace the "Quick start" and "Development" sections with the verified commands and add an API section:

````markdown
## Quick start

```bash
uv sync --all-groups
cp .env.example .env               # optional; defaults work out of the box
uv run jobscout fetch              # pull jobs from enabled sources into ./jobscout.db
uv run jobscout jobs               # jobs that pass your preferences (newest first)
uv run jobscout jobs --all         # every active job, ignoring preferences
uv run jobscout serve              # API + Swagger UI at http://127.0.0.1:8000/docs
```

Set your preferences through the API (`PUT /preferences`), e.g.

```json
{ "titles": ["AI Engineer", "Machine Learning Engineer"], "work_modes": ["remote"], "regions": ["Germany", "Portugal"] }
```

## API

| Method | Path            | Description                                   |
|--------|-----------------|-----------------------------------------------|
| GET    | `/health`       | Liveness                                      |
| GET    | `/jobs`         | Active jobs passing your preferences (`?all=true` to ignore them, `?limit=`) |
| GET    | `/preferences`  | Current preferences                           |
| PUT    | `/preferences`  | Partial update; only sent fields change       |

## Development

```bash
uv run pytest                      # unit tests, no network
uv run pytest -m integration       # opt-in tests against real APIs
uv run pytest tests/sources/test_arbeitnow.py::test_fetch_maps_fields   # single test
uv run ruff check . && uv run ruff format .
```

Adding a job source: implement `JobSource` in `src/jobscout/sources/<name>.py` returning `RawJob`s,
register it in `sources/registry.py`, add `tests/fixtures/<name>_sample.json` and one line in
`tests/sources/test_contract.py`. The contract test does the rest.
````

- [ ] **Step 4: Update `CLAUDE.md`**

Replace the **Current state** paragraph with:
```markdown
## Current state

Stages 0 and 1 are implemented (see `docs/superpowers/plans/2026-09-20-stage-0-1-foundation-and-vertical-slice.md`). Next is stage 2 (LangGraph matching). The design source of truth is `docs/superpowers/specs/2026-09-19-jobscout-design.md`; `job-radar-contexto.md` is the original Portuguese brainstorm.
```

Replace the **Commands** section with:
```markdown
## Commands

- `uv sync --all-groups` — install (Python 3.12 is pinned in `.python-version`; never use the system Python).
- `uv run pytest` — unit tests, no network. Single test: `uv run pytest tests/sources/test_arbeitnow.py::test_fetch_maps_fields -v`.
- `uv run pytest -m integration` — opt-in tests against real APIs (off by default via `addopts`).
- `uv run ruff check .` / `uv run ruff format .` — lint/format; both must be clean before committing.
- `uv run jobscout fetch|jobs|serve` — CLI. `serve` runs uvicorn on `jobscout.api.app:app`.
- CI (`.github/workflows/ci.yml`) runs ruff check, ruff format --check and pytest.
```

- [ ] **Step 5: Final full verification and commit**

Run: `uv run ruff check . ; uv run ruff format --check . ; uv run pytest -q`
Expected: clean lint, all tests pass.
```powershell
git add tests/integration README.md CLAUDE.md
git commit -m "docs: document commands, API and source contribution; add opt-in live Arbeitnow test" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Publish (ask the user first)**

Creating the GitHub repository is an outward-facing action — confirm with the user before running:
```powershell
gh repo create jobscout --public --source . --remote origin --push
```
Then check that the CI run is green at the Actions tab. If it is not, fix and push before calling stage 1 done.

---

## Self-review against the spec

- **Stage 0 deliverables** — Task 1 (uv, src-layout, ruff, pytest), Task 2 (CI, MIT, README, .env.example), Task 14 (CLAUDE.md commands). ✔
- **Stage 1 deliverables** — Settings (T3); models + SQLite (T4); `JobSource` + Arbeitnow (T5–T6); registry + contract test (T7); upsert with dedup/liveness/content_hash (T8); deterministic filter (T9); fixed current user (T10, T13); CLI `fetch`/`jobs`/`serve` (T12); API `GET /jobs`, `GET/PUT /preferences` (T13); operator vs. user config separation (T3 vs. T4/T10). ✔
- **Spec deviations, stated:** `JobSource.fetch` takes a `SearchQuery` derived from preferences instead of `UserPreferences` itself, so sources never import DB models (spec §4 dependency rule wins over §4 signature wording). `UserPreferences.excluded_keywords` added to support the spec's "hard keyword exclusions" (§5 step 3). Marking `Match` rows `stale` on content change is deferred to stage 2 because `Match` does not exist yet; `Job.embedding` is already cleared (T8).
- **Not in this plan (later stages by design):** `Match`, matching graph, backfill, scheduler, inactive marking, notifiers, more sources, UI, auth, Postgres/Docker, i18n, quotas, BYOK.
- **Type/name consistency check:** `RawJob`/`SearchQuery` (T5) used identically in T6–T8, T11–T13; `IngestResult` fields (`source, fetched, created, updated, changed, error`) match CLI output in T12; `list_jobs(session, user_id, limit, apply_filters, active_only)` signature identical in T11, T12, T13; `get_or_create_default_user`, `get_preferences`, `update_preferences` identical in T10–T13; `create_engine_from_url`/`init_db`/`get_engine` identical in T4, T12, T13.

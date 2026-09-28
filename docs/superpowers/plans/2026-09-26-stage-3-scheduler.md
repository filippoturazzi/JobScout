# Stage 3 — Scheduler and inactive marking: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make JobScout collect and score jobs on its own schedule inside the API process, expire postings nobody has seen in a while, and let the operator prove it is working.

**Architecture:** An APScheduler `BackgroundScheduler` lives in the FastAPI lifespan and runs two independent jobs — `ingest_job` (global, 60 min) and `match_job` (all users, 15 min). Both are plain functions over `pipeline/`, so all logic is tested without a scheduler. Every execution writes a `Run` row, which is also what the failure backoff reads. `PUT /preferences` stops matching inline and instead wakes the match job.

**Tech Stack:** Python 3.12, `uv`, APScheduler 3.x, SQLModel, FastAPI, pytest, ruff, mypy `--strict`.

**Spec:** `docs/superpowers/specs/2026-09-26-stage-3-scheduler-design.md`

## Global Constraints

- Python 3.12, pinned in `.python-version`. Never use the system Python; every command goes through `uv run`.
- `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy src` must all be clean before every commit. CI enforces all three.
- Tests never touch the network. No test sleeps, waits for a scheduler tick, or lets real time pass.
- All timestamps are naive UTC via `jobscout.models.base.utcnow()`. SQLite discards tzinfo on read, so aware datetimes break comparisons between fresh and loaded values.
- Operator config (env, `Settings`) is strictly separate from user preferences (DB). Every setting added here is operator config.
- Dependency direction: `sources` (no DB) · `matching` (no HTTP) · `pipeline` (the only composer) · `api`, `cli`, `scheduler` are thin shells over `pipeline`.
- Commit messages end with: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
- English for code, comments and docs.

## Review Focus

Five conditions the spec implies but that no task's happy path exercises. Each has a test assigned to the task that owns the code.

1. **A scheduler thread and an HTTP request call `get_engine()` at the same time** — under `StaticPool` in-memory this can produce two different databases, not just a wasted pool. Expected: one engine per URL, always. (Task 1)
2. **A source returns an error in the same execution where another succeeds** — expected: only the successful source's stale jobs are deactivated; the failed source's catalogue is untouched. (Task 3)
3. **A job raises after its `Run` row was created** — expected: the row survives with `ok=False` and the message, rather than being rolled back into invisibility. (Task 7)
4. **The backoff skips a tick** — expected: no `Run` row is written, so skipping cannot itself deepen the backoff into a permanent stall. (Task 7)
5. **`wake_matching()` is called when no scheduler exists** (CLI, or API with `SCHEDULER_ENABLED=false`) — expected: a no-op, never an exception out of `PUT /preferences`. (Task 8)

---

### Task 1: Thread-safe engine cache

**Files:**
- Modify: `src/jobscout/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `get_engine(settings: Settings | None = None) -> Engine`, unchanged signature, now safe to call from several threads.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
import threading

from jobscout.db import get_engine, reset_engines


def test_get_engine_returns_one_engine_under_concurrent_callers():
    """The scheduler thread and a request can race here; two StaticPool engines
    would be two different in-memory databases, not just a wasted pool."""
    reset_engines()
    settings = Settings(_env_file=None, database_url="sqlite://")
    engines = []
    barrier = threading.Barrier(8)

    def grab():
        barrier.wait()
        engines.append(get_engine(settings))

    threads = [threading.Thread(target=grab) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len({id(engine) for engine in engines}) == 1
```

Import `Settings` from `jobscout.config` if the file does not already.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_get_engine_returns_one_engine_under_concurrent_callers -v`

Expected: FAIL, or flaky. A `threading.Barrier` makes all eight threads reach `get_engine` together, so the `if url not in _engines` check races. If it happens to pass, run it a few times — the point of the test is that it is guaranteed after the fix, not that it fails every time before.

- [ ] **Step 3: Write minimal implementation**

In `src/jobscout/db.py`, add the import and lock, and guard the cache:

```python
import threading

_engines: dict[str, Engine] = {}
_engines_lock = threading.Lock()


def get_engine(settings: Settings | None = None) -> Engine:
    """One engine per DATABASE_URL, shared by the CLI, the API lifespan and the scheduler."""
    url = (settings or get_settings()).database_url
    with _engines_lock:
        if url not in _engines:
            _engines[url] = create_engine_from_url(url)
        return _engines[url]


def reset_engines() -> None:
    """Dispose and forget every cached engine (tests, or after changing settings)."""
    with _engines_lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS, including the existing engine tests.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/db.py tests/test_db.py
git commit -m "fix: guard the engine cache with a lock for the scheduler thread"
```

---

### Task 2: The `Run` model

**Files:**
- Create: `src/jobscout/models/run.py`
- Modify: `src/jobscout/models/__init__.py`
- Test: `tests/test_run_model.py`

**Interfaces:**
- Consumes: `jobscout.models.base.utcnow`.
- Produces:
  - `Run` SQLModel table with fields `id: int | None`, `job: str`, `started_at: datetime`, `finished_at: datetime | None`, `ok: bool`, `error: str | None`, `counters: dict[str, int]`.
  - `RUN_JOBS: frozenset[str]` = `{"ingest", "match"}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_model.py`:

```python
from sqlmodel import Session, select

from jobscout.models import RUN_JOBS, Run
from jobscout.models.base import utcnow


def test_run_defaults_to_an_unfinished_failure():
    """A row is written before the work starts, so the default must be the pessimistic one:
    a process killed mid-run leaves a trace that reads as a failure, not a success."""
    run = Run(job="ingest")

    assert run.ok is False
    assert run.finished_at is None
    assert run.counters == {}


def test_run_round_trips_counters(session: Session):
    session.add(Run(job="match", counters={"evaluated": 3, "skipped_low": 7}))
    session.commit()

    stored = session.exec(select(Run)).one()

    assert stored.counters == {"evaluated": 3, "skipped_low": 7}
    assert stored.started_at <= utcnow()


def test_run_jobs_lists_both_scheduled_jobs():
    assert RUN_JOBS == frozenset({"ingest", "match"})
```

The `session` fixture already exists in `tests/conftest.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_run_model.py -v`
Expected: FAIL with `ImportError: cannot import name 'RUN_JOBS' from 'jobscout.models'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/jobscout/models/run.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from jobscout.models.base import utcnow

RUN_JOBS: frozenset[str] = frozenset({"ingest", "match"})
"""The scheduled jobs that record a run. Stage 4 adds the notifier."""


class Run(SQLModel, table=True):
    """One execution of one scheduled job.

    The row is created before the work starts and finished afterwards, so `ok=False` with
    no `finished_at` is what a killed process leaves behind. `counters` is a JSON blob
    because the two jobs report different things.
    """

    id: int | None = Field(default=None, primary_key=True)
    job: str = Field(index=True)
    started_at: datetime = Field(default_factory=utcnow, nullable=False, index=True)
    finished_at: datetime | None = None
    ok: bool = False
    error: str | None = None
    counters: dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
```

In `src/jobscout/models/__init__.py`, add `from jobscout.models.run import RUN_JOBS, Run` and add `"RUN_JOBS"` and `"Run"` to `__all__`, keeping the existing alphabetical ordering of that list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_run_model.py -v && uv run mypy src`
Expected: PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/models/run.py src/jobscout/models/__init__.py tests/test_run_model.py
git commit -m "feat: add the Run table that records each scheduled execution"
```

---

### Task 3: Deactivate stale jobs, per source

**Files:**
- Create: `src/jobscout/pipeline/liveness.py`
- Test: `tests/pipeline/test_liveness.py`

**Interfaces:**
- Consumes: `Job`, `Settings.inactive_after_days`, `utcnow`.
- Produces: `deactivate_stale_jobs(session: Session, settings: Settings, source: str) -> int` — returns how many rows it flipped. Does **not** commit; the caller owns the transaction.

- [ ] **Step 1: Write the failing test**

Create `tests/pipeline/test_liveness.py`:

```python
from datetime import timedelta

from sqlmodel import Session, select

from jobscout.config import Settings
from jobscout.models import Job
from jobscout.models.base import utcnow
from jobscout.pipeline.liveness import deactivate_stale_jobs


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _add_job(session: Session, source: str, external_id: str, days_ago: int) -> Job:
    seen = utcnow() - timedelta(days=days_ago)
    job = Job(
        source=source,
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        remote=True,
        url=f"https://x/{external_id}",
        description="Python LLM work.",
        content_hash=f"h-{external_id}",
        first_seen_at=seen,
        last_seen_at=seen,
        is_active=True,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_deactivates_only_jobs_older_than_the_window(session: Session):
    old = _add_job(session, "arbeitnow", "old", days_ago=20)
    fresh = _add_job(session, "arbeitnow", "fresh", days_ago=3)

    flipped = deactivate_stale_jobs(session, _settings(inactive_after_days=14), "arbeitnow")
    session.commit()

    assert flipped == 1
    assert session.get(Job, old.id).is_active is False
    assert session.get(Job, fresh.id).is_active is True


def test_leaves_other_sources_alone(session: Session):
    """The caller only passes sources that answered; a source that errored must keep
    its catalogue. 'I did not ask' is not 'it no longer exists'."""
    mine = _add_job(session, "arbeitnow", "mine", days_ago=20)
    theirs = _add_job(session, "remotive", "theirs", days_ago=20)

    flipped = deactivate_stale_jobs(session, _settings(inactive_after_days=14), "arbeitnow")
    session.commit()

    assert flipped == 1
    assert session.get(Job, mine.id).is_active is False
    assert session.get(Job, theirs.id).is_active is True


def test_already_inactive_jobs_are_not_counted_again(session: Session):
    job = _add_job(session, "arbeitnow", "old", days_ago=20)
    job.is_active = False
    session.add(job)
    session.commit()

    flipped = deactivate_stale_jobs(session, _settings(inactive_after_days=14), "arbeitnow")
    session.commit()

    assert flipped == 0


def test_does_not_commit_on_its_own(session: Session):
    """The caller owns the transaction: the ingest job batches this with its Run row."""
    job = _add_job(session, "arbeitnow", "old", days_ago=20)

    deactivate_stale_jobs(session, _settings(inactive_after_days=14), "arbeitnow")
    session.rollback()

    assert session.get(Job, job.id).is_active is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/pipeline/test_liveness.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.pipeline.liveness'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/jobscout/pipeline/liveness.py`:

```python
"""Expiring postings nobody has seen lately. Separate from ingest, which brings data in."""

from datetime import timedelta

from sqlmodel import Session, col, select, update

from jobscout.config import Settings
from jobscout.models import Job
from jobscout.models.base import utcnow


def deactivate_stale_jobs(session: Session, settings: Settings, source: str) -> int:
    """Mark one source's unseen jobs inactive. Returns the number of rows flipped.

    Scoped to a single source on purpose: the caller passes only sources that answered,
    so a source that is down or was removed from SOURCES never expires its catalogue.
    Does not commit — the caller batches this with its own bookkeeping.
    """
    cutoff = utcnow() - timedelta(days=settings.inactive_after_days)
    stale = select(col(Job.id)).where(
        col(Job.source) == source,
        col(Job.is_active).is_(True),
        col(Job.last_seen_at) < cutoff,
    )
    ids = list(session.exec(stale).all())
    if not ids:
        return 0
    session.exec(update(Job).where(col(Job.id).in_(ids)).values(is_active=False))
    return len(ids)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/pipeline/test_liveness.py -v && uv run mypy src`
Expected: PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/pipeline/liveness.py tests/pipeline/test_liveness.py
git commit -m "feat: deactivate a source's unseen jobs, scoped to that source"
```

---

### Task 4: Scheduler settings and the APScheduler dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/jobscout/config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces on `Settings`: `scheduler_enabled: bool = True`, `ingest_interval_minutes: int = 60`, `match_interval_minutes: int = 15`, `scheduler_jitter_seconds: int = 30`, `run_retention_days: int = 30`, `max_backoff_ticks: int = 6`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_scheduler_settings_have_operator_defaults():
    settings = Settings(_env_file=None)

    assert settings.scheduler_enabled is True
    assert settings.ingest_interval_minutes == 60
    assert settings.match_interval_minutes == 15
    assert settings.scheduler_jitter_seconds == 30
    assert settings.run_retention_days == 30
    assert settings.max_backoff_ticks == 6


def test_scheduler_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")

    assert Settings(_env_file=None).scheduler_enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'scheduler_enabled'`.

- [ ] **Step 3: Write minimal implementation**

Add the dependency:

```bash
uv add "apscheduler>=3.10,<4"
```

APScheduler 4 is a rewrite with a different API; the `<4` bound is deliberate.

In `src/jobscout/config.py`, add these fields next to the other operator settings, after `backfill_window_days`:

```python
    scheduler_enabled: bool = True
    ingest_interval_minutes: int = 60
    match_interval_minutes: int = 15
    scheduler_jitter_seconds: int = 30
    run_retention_days: int = 30
    max_backoff_ticks: int = 6
```

In `.env.example`, add a commented block:

```bash
# --- Scheduler (stage 3) ---
# The scheduler runs inside `jobscout serve`. The CLI stays manual.
# SCHEDULER_ENABLED=true
# Ingest is cheap HTTP; matching spends LLM and embedding quota, so they have
# separate intervals.
# INGEST_INTERVAL_MINUTES=60
# MATCH_INTERVAL_MINUTES=15
# Spread firings so two jobs do not land on the same second.
# SCHEDULER_JITTER_SECONDS=30
# Run rows older than this are pruned when a new run starts.
# RUN_RETENTION_DAYS=30
# After k consecutive failures a job runs every 2**k ticks, capped here.
# MAX_BACKOFF_TICKS=6
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v && uv run mypy src && uv lock --check`
Expected: PASS, mypy clean, lock consistent.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/jobscout/config.py .env.example tests/test_config.py
git commit -m "feat: add scheduler settings and the APScheduler dependency"
```

---

### Task 5: Run bookkeeping — start, finish, prune

**Files:**
- Create: `src/jobscout/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `Run`, `Settings.run_retention_days`.
- Produces:
  - `start_run(session: Session, settings: Settings, job: str) -> Run` — creates and commits the row, prunes old rows in the same transaction.
  - `finish_run(session: Session, run: Run, ok: bool, counters: dict[str, int], error: str | None = None) -> None` — commits.

This task creates `scheduler.py` with only the bookkeeping helpers. Tasks 6-8 add the rest to the same file.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scheduler.py`:

```python
from datetime import timedelta

from sqlmodel import Session, select

from jobscout.config import Settings
from jobscout.models import Run
from jobscout.models.base import utcnow
from jobscout.scheduler import finish_run, start_run


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_start_run_writes_a_pessimistic_row(session: Session):
    """The row lands before the work does, so a killed process leaves a failure behind."""
    run = start_run(session, _settings(), "ingest")

    stored = session.exec(select(Run)).one()
    assert (stored.id, stored.job, stored.ok, stored.finished_at) == (run.id, "ingest", False, None)


def test_finish_run_records_counters(session: Session):
    run = start_run(session, _settings(), "match")

    finish_run(session, run, ok=True, counters={"evaluated": 4})

    stored = session.exec(select(Run)).one()
    assert (stored.ok, stored.counters, stored.error) == (True, {"evaluated": 4}, None)
    assert stored.finished_at is not None


def test_finish_run_records_the_failure_message(session: Session):
    run = start_run(session, _settings(), "match")

    finish_run(session, run, ok=False, counters={}, error="RuntimeError: 429")

    stored = session.exec(select(Run)).one()
    assert (stored.ok, stored.error) == (False, "RuntimeError: 429")


def test_start_run_prunes_rows_past_the_retention_window(session: Session):
    old = Run(job="ingest", started_at=utcnow() - timedelta(days=40), ok=True)
    recent = Run(job="ingest", started_at=utcnow() - timedelta(days=5), ok=True)
    session.add(old)
    session.add(recent)
    session.commit()

    start_run(session, _settings(run_retention_days=30), "ingest")

    remaining = session.exec(select(Run)).all()
    assert len(remaining) == 2, "the 40-day-old row is gone; the 5-day-old one and the new one stay"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.scheduler'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/jobscout/scheduler.py`:

```python
"""The scheduled half of JobScout. A thin composer over `pipeline/`, like the API and CLI.

Every execution is recorded in a `Run` row, which is also what the failure backoff reads.
The job functions are plain callables so all logic is testable without a scheduler.
"""

import logging
from datetime import timedelta

from sqlmodel import Session, col, delete

from jobscout.config import Settings
from jobscout.models import Run
from jobscout.models.base import utcnow

log = logging.getLogger(__name__)


def start_run(session: Session, settings: Settings, job: str) -> Run:
    """Open a run and prune expired history in the same transaction.

    The row is written before the work starts and defaults to `ok=False`, so a process
    killed mid-run leaves a trace that reads as a failure rather than vanishing.
    """
    cutoff = utcnow() - timedelta(days=settings.run_retention_days)
    session.exec(delete(Run).where(col(Run.started_at) < cutoff))
    run = Run(job=job)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def finish_run(
    session: Session,
    run: Run,
    ok: bool,
    counters: dict[str, int],
    error: str | None = None,
) -> None:
    run.ok = ok
    run.counters = counters
    run.error = error
    run.finished_at = utcnow()
    session.add(run)
    session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scheduler.py -v && uv run mypy src`
Expected: PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/scheduler.py tests/test_scheduler.py
git commit -m "feat: record each scheduled execution as a Run row"
```

---

### Task 6: The failure backoff

**Files:**
- Modify: `src/jobscout/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `Run`, `Settings.max_backoff_ticks`.
- Produces: `should_skip_for_backoff(session: Session, settings: Settings, job: str, tick: int) -> bool`. Pure with respect to its arguments; no scheduler needed to test it.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scheduler.py`:

```python
import pytest

from jobscout.scheduler import should_skip_for_backoff


def _record(session: Session, job: str, ok: bool) -> None:
    session.add(Run(job=job, ok=ok, finished_at=utcnow()))
    session.commit()


def test_no_history_never_skips(session: Session):
    assert should_skip_for_backoff(session, _settings(), "match", tick=1) is False


@pytest.mark.parametrize("tick,expected", [(1, True), (2, False), (3, True), (4, False)])
def test_one_failure_halves_the_rate(session: Session, tick: int, expected: bool):
    _record(session, "match", ok=False)

    assert should_skip_for_backoff(session, _settings(), "match", tick=tick) is expected


def test_failures_compound(session: Session):
    """Three consecutive failures means every 8th tick."""
    for _ in range(3):
        _record(session, "match", ok=False)

    assert should_skip_for_backoff(session, _settings(), "match", tick=7) is True
    assert should_skip_for_backoff(session, _settings(), "match", tick=8) is False


def test_a_success_resets_the_count(session: Session):
    for _ in range(3):
        _record(session, "match", ok=False)
    _record(session, "match", ok=True)

    assert should_skip_for_backoff(session, _settings(), "match", tick=1) is False


def test_the_backoff_is_capped(session: Session):
    for _ in range(40):
        _record(session, "match", ok=False)

    settings = _settings(max_backoff_ticks=2)

    assert should_skip_for_backoff(session, settings, "match", tick=4) is False, "2**2, not 2**40"


def test_another_jobs_failures_do_not_slow_this_one(session: Session):
    for _ in range(5):
        _record(session, "ingest", ok=False)

    assert should_skip_for_backoff(session, _settings(), "match", tick=1) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: FAIL with `ImportError: cannot import name 'should_skip_for_backoff'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/jobscout/scheduler.py` (and extend the `sqlmodel` import to include `desc` and `select`):

```python
def should_skip_for_backoff(session: Session, settings: Settings, job: str, tick: int) -> bool:
    """Should this firing be skipped because the job keeps failing?

    Backoff triggers on consecutive failure, not on a 429 specifically: matching a provider's
    rate-limit wording breaks when the wording changes, and it misses the other reasons to
    stop hammering — network, auth, a daily quota. With `k` consecutive failures the job runs
    only every `2**k`-th tick, capped by MAX_BACKOFF_TICKS.

    A skipped tick writes no Run row, so skipping can never deepen the backoff by itself.
    """
    recent = session.exec(
        select(Run).where(col(Run.job) == job).order_by(desc(col(Run.started_at))).limit(64)
    ).all()
    failures = 0
    for run in recent:
        if run.ok:
            break
        failures += 1
    if failures == 0:
        return False
    every = 2 ** min(failures, settings.max_backoff_ticks)
    return tick % every != 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scheduler.py -v && uv run mypy src`
Expected: PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/scheduler.py tests/test_scheduler.py
git commit -m "feat: back off a job that keeps failing"
```

---

### Task 7: The two job functions

**Files:**
- Modify: `src/jobscout/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `run_ingest(session, settings, sources=None) -> list[IngestResult]` (each carries `source`, `created`, `updated`, `changed`, `error`); `deactivate_stale_jobs(session, settings, source) -> int`; `run_match(session, settings, user_id, limit=None, dry_run=False, deps=None) -> MatchRun`; `start_run`; `finish_run`; `should_skip_for_backoff`.
- Produces:
  - `ingest_job(engine: Engine, settings: Settings) -> None`
  - `match_job(engine: Engine, settings: Settings, tick: int = 0) -> None`

Both open and close their own `Session`, catch every exception, and record it. Neither raises.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scheduler.py`:

```python
from jobscout.db import get_engine
from jobscout.models import Job, Match
from jobscout.pipeline.users import get_or_create_default_user, update_preferences
from jobscout.scheduler import ingest_job, match_job
from tests.matching.fakes import CountingChatModel, DeterministicFakeEmbedding
```

```python
def test_ingest_job_records_counters_and_deactivates(session: Session, monkeypatch):
    """A source that answered expires its own stale jobs; a source that errored keeps its own."""
    import jobscout.scheduler as scheduler_module

    engine = session.get_bind()
    stale_ok = _add_stale_job(session, "arbeitnow", "gone", days_ago=30)
    stale_broken = _add_stale_job(session, "remotive", "kept", days_ago=30)

    def _fake_ingest(_session, _settings, sources=None):
        from jobscout.pipeline.ingest import IngestResult

        return [
            IngestResult(source="arbeitnow", fetched=5, created=2, updated=3),
            IngestResult(source="remotive", error="HTTPStatusError: 503"),
        ]

    monkeypatch.setattr(scheduler_module, "run_ingest", _fake_ingest)

    ingest_job(engine, _settings(inactive_after_days=14))

    stored = session.exec(select(Run).where(col(Run.job) == "ingest")).one()
    assert stored.ok is True
    assert stored.counters["created"] == 2
    assert stored.counters["deactivated"] == 1
    session.expire_all()
    assert session.get(Job, stale_ok.id).is_active is False
    assert session.get(Job, stale_broken.id).is_active is True


def test_ingest_job_records_a_crash_instead_of_raising(session: Session, monkeypatch):
    """A raising job must leave its Run row behind with the message, not roll it away."""
    import jobscout.scheduler as scheduler_module

    def _boom(*_args, **_kwargs):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(scheduler_module, "run_ingest", _boom)

    ingest_job(session.get_bind(), _settings())

    stored = session.exec(select(Run)).one()
    assert (stored.ok, stored.error) == (False, "RuntimeError: connection reset")
    assert stored.finished_at is not None


def test_match_job_skipped_by_backoff_writes_no_row(session: Session):
    """Skipping must not itself count as a failure, or the backoff would stall forever."""
    _record(session, "match", ok=False)

    match_job(session.get_bind(), _settings(), tick=1)

    assert session.exec(select(Run).where(col(Run.job) == "match")).all() == []
```

Add this helper next to the others in the file:

```python
def _add_stale_job(session: Session, source: str, external_id: str, days_ago: int) -> Job:
    seen = utcnow() - timedelta(days=days_ago)
    job = Job(
        source=source,
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        remote=True,
        url=f"https://x/{external_id}",
        description="Python LLM work.",
        content_hash=f"h-{external_id}",
        first_seen_at=seen,
        last_seen_at=seen,
        is_active=True,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: FAIL with `ImportError: cannot import name 'ingest_job'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/jobscout/scheduler.py`, extending the imports with `Engine` from `sqlalchemy`, `select` from `sqlmodel`, `User` from `jobscout.models`, and the pipeline entry points:

```python
def ingest_job(engine: Engine, settings: Settings) -> None:
    """Fetch every configured source, then expire what the answering sources stopped showing."""
    with Session(engine) as session:
        run = start_run(session, settings, "ingest")
        counters = {"created": 0, "updated": 0, "changed": 0, "deactivated": 0}
        try:
            results = run_ingest(session, settings)
            errors = []
            for result in results:
                if result.error is not None:
                    errors.append(f"{result.source}: {result.error}")
                    continue
                counters["created"] += result.created
                counters["updated"] += result.updated
                counters["changed"] += result.changed
                # Only a source that answered may expire its own postings.
                counters["deactivated"] += deactivate_stale_jobs(session, settings, result.source)
            session.commit()
        except Exception as exc:
            session.rollback()
            log.exception("ingest job failed")
            finish_run(session, run, ok=False, counters=counters, error=f"{type(exc).__name__}: {exc}")
            return
        finish_run(
            session, run, ok=not errors, counters=counters, error="; ".join(errors) or None
        )


def match_job(engine: Engine, settings: Settings, tick: int = 0) -> None:
    """Score what is pending, for every user, within the per-run caps."""
    with Session(engine) as session:
        if should_skip_for_backoff(session, settings, "match", tick):
            log.info("match job skipped by backoff at tick %s", tick)
            return
        run = start_run(session, settings, "match")
        counters = {
            "candidates": 0,
            "evaluated": 0,
            "skipped_low": 0,
            "embedded": 0,
            "embeddings_pending": 0,
            "errors": 0,
        }
        try:
            user_ids = [uid for uid in session.exec(select(col(User.id))).all() if uid is not None]
            messages = []
            for user_id in user_ids:
                result = run_match(session, settings, user_id)
                counters["candidates"] += result.candidates
                counters["evaluated"] += result.evaluated
                counters["skipped_low"] += result.skipped_low
                counters["embedded"] += result.embedded
                counters["embeddings_pending"] += result.embeddings_pending
                counters["errors"] += len(result.errors)
                if result.error is not None:
                    messages.append(f"user {user_id}: {result.error}")
        except Exception as exc:
            session.rollback()
            log.exception("match job failed")
            finish_run(session, run, ok=False, counters=counters, error=f"{type(exc).__name__}: {exc}")
            return
        finish_run(
            session, run, ok=not messages, counters=counters, error="; ".join(messages) or None
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scheduler.py -v && uv run mypy src`
Expected: PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/scheduler.py tests/test_scheduler.py
git commit -m "feat: add the ingest and match scheduled jobs"
```

---

### Task 8: `JobScoutScheduler` — wiring and wake

**Files:**
- Modify: `src/jobscout/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Produces:
  - `JobScoutScheduler(engine: Engine, settings: Settings)`
  - `.start() -> None` — registers both jobs and starts the underlying `BackgroundScheduler`; a no-op when `settings.scheduler_enabled` is false.
  - `.shutdown() -> None` — safe to call when never started.
  - `.get_jobs() -> list[Job]` — APScheduler's job objects, for tests and `/runs` diagnostics.
  - `.wake_matching() -> None` — schedules one immediate `match_job`, id `match-wake`, replacing any pending one.
  - Module-level `wake_matching(scheduler: JobScoutScheduler | None) -> None` — the no-op-friendly entry point the API calls.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scheduler.py`:

```python
from jobscout.scheduler import JobScoutScheduler, wake_matching


def test_start_registers_both_jobs_at_the_configured_intervals(session: Session):
    scheduler = JobScoutScheduler(
        session.get_bind(), _settings(ingest_interval_minutes=42, match_interval_minutes=7)
    )
    scheduler.start()
    try:
        by_id = {job.id: job for job in scheduler.get_jobs()}

        assert set(by_id) == {"ingest", "match"}
        assert by_id["ingest"].trigger.interval.total_seconds() == 42 * 60
        assert by_id["match"].trigger.interval.total_seconds() == 7 * 60
    finally:
        scheduler.shutdown()


def test_disabled_scheduler_registers_nothing(session: Session):
    """Otherwise every test that builds the app would start threads."""
    scheduler = JobScoutScheduler(session.get_bind(), _settings(scheduler_enabled=False))
    scheduler.start()
    try:
        assert scheduler.get_jobs() == []
    finally:
        scheduler.shutdown()


def test_wake_adds_one_immediate_run_and_repeats_collapse(session: Session):
    scheduler = JobScoutScheduler(session.get_bind(), _settings())
    scheduler.start()
    try:
        scheduler.wake_matching()
        scheduler.wake_matching()

        wakes = [job for job in scheduler.get_jobs() if job.id == "match-wake"]
        assert len(wakes) == 1, "a second save must replace the pending run, not queue another"
    finally:
        scheduler.shutdown()


def test_wake_without_a_scheduler_is_a_no_op():
    """The CLI and a scheduler-less API both call this; it must never raise."""
    wake_matching(None)


def test_shutdown_is_safe_before_start(session: Session):
    JobScoutScheduler(session.get_bind(), _settings()).shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: FAIL with `ImportError: cannot import name 'JobScoutScheduler'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/jobscout/scheduler.py`:

```python
class JobScoutScheduler:
    """Owns the APScheduler instance and the per-job tick counters.

    No persistent jobstore: jobs are registered from Settings at every startup, so a
    schedule from an old configuration can never outlive the configuration that made it.
    """

    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings
        self._scheduler = BackgroundScheduler()
        self._match_tick = 0

    def _run_ingest_tick(self) -> None:
        ingest_job(self._engine, self._settings)

    def _run_match_tick(self) -> None:
        self._match_tick += 1
        match_job(self._engine, self._settings, tick=self._match_tick)

    def start(self) -> None:
        if not self._settings.scheduler_enabled:
            log.info("scheduler disabled by SCHEDULER_ENABLED")
            return
        jitter = self._settings.scheduler_jitter_seconds
        self._scheduler.add_job(
            self._run_ingest_tick,
            "interval",
            minutes=self._settings.ingest_interval_minutes,
            id="ingest",
            max_instances=1,
            coalesce=True,
            jitter=jitter,
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._run_match_tick,
            "interval",
            minutes=self._settings.match_interval_minutes,
            id="match",
            max_instances=1,
            coalesce=True,
            jitter=jitter,
            replace_existing=True,
        )
        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def get_jobs(self) -> list[APSJob]:
        return list(self._scheduler.get_jobs())

    def wake_matching(self) -> None:
        """Run matching now, out of band. Repeated calls collapse into one pending run."""
        if not self._scheduler.running:
            return
        self._scheduler.add_job(
            self._run_match_tick,
            "date",
            run_date=utcnow(),
            id="match-wake",
            replace_existing=True,
            misfire_grace_time=None,
        )


def wake_matching(scheduler: "JobScoutScheduler | None") -> None:
    """Ask the scheduler to match now, if there is one. A no-op otherwise.

    The CLI has no scheduler, and the API runs without one when SCHEDULER_ENABLED is false.
    Saving preferences must not fail because of that.
    """
    if scheduler is not None:
        scheduler.wake_matching()
```

Extend the imports at the top of the file:

```python
from apscheduler.job import Job as APSJob
from apscheduler.schedulers.background import BackgroundScheduler
```

Note the `_run_match_tick` indirection: `wake_matching` reuses it so a woken run advances the same tick counter as a scheduled one.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scheduler.py -v && uv run mypy src`
Expected: PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/scheduler.py tests/test_scheduler.py
git commit -m "feat: wire the scheduler and let a preference save wake matching"
```

---

### Task 9: Take the backfill out of `PUT /preferences`

**Files:**
- Modify: `src/jobscout/pipeline/run.py`
- Modify: `src/jobscout/api/routers/preferences.py`
- Modify: `tests/pipeline/test_backfill.py`
- Modify: `tests/api/test_preferences.py`

**Interfaces:**
- Changes: `save_preferences(session, settings, user_id, changes, on_changed: Callable[[], None] | None = None) -> tuple[UserPreferences, MatchRun]`. It no longer calls `backfill_matches`; it stales and calls `on_changed()` if given. `_BACKFILL_EVALUATION_CAP` is deleted. The returned `MatchRun` is always empty — kept so the signature does not churn for callers and so stage 6 can put the woken run's outcome there.

- [ ] **Step 1: Write the failing test**

Replace the backfill-related tests in `tests/pipeline/test_backfill.py` with:

```python
def test_save_preferences_stales_without_evaluating_anything(session):
    """Matching moved to the scheduler: a save must not call a provider at all."""
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    job = _add_job(session, "a")
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, score=50, status="seen"))
    session.commit()
    chat = CountingChatModel()

    _, run = save_preferences(
        session, _settings(), user.id, {"titles": ["AI Engineer"]}, deps=_deps(chat)
    )

    assert chat.calls == 0
    assert run.evaluated == 0
    assert session.exec(select(Match)).one().status == "stale"


def test_save_preferences_wakes_the_scheduler(session):
    user = get_or_create_default_user(session)
    woken = []

    save_preferences(
        session,
        _settings(),
        user.id,
        {"profile_summary": "Python LLM engineer."},
        on_changed=lambda: woken.append(True),
    )

    assert woken == [True]


def test_save_preferences_does_not_wake_on_an_irrelevant_change(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    woken = []

    save_preferences(
        session, _settings(), user.id, {"min_score_to_notify": 80}, on_changed=lambda: woken.append(True)
    )

    assert woken == []


def test_save_preferences_survives_a_failing_wake(session):
    """A broken scheduler must not lose a preference save."""
    user = get_or_create_default_user(session)

    def _boom() -> None:
        raise RuntimeError("scheduler is down")

    prefs, run = save_preferences(
        session, _settings(), user.id, {"profile_summary": "Python."}, on_changed=_boom
    )

    assert prefs.profile_summary == "Python."
    assert run.error == "RuntimeError: scheduler is down"
```

Delete `test_save_preferences_caps_the_backfill_so_the_request_stays_interactive` and `test_save_preferences_never_spends_more_than_the_operator_allowed`: both pin the inline backfill this task removes. Keep the two parametrized rollback tests but retarget them at the `on_changed` failure path.

Check whether `min_score_to_notify` is in `MATCHING_RELEVANT_FIELDS` in `pipeline/users.py`; if it is, use a different irrelevant field in the third test.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/pipeline/test_backfill.py -v`
Expected: FAIL — `save_preferences` has no `on_changed` parameter.

- [ ] **Step 3: Write minimal implementation**

In `src/jobscout/pipeline/run.py`: delete `_BACKFILL_EVALUATION_CAP` and its comment block, drop the `backfill_matches` import if nothing else uses it, and rewrite the tail of `save_preferences`:

```python
def save_preferences(
    session: Session,
    settings: Settings,
    user_id: int,
    changes: dict[str, Any],
    deps: GraphDeps | None = None,
    on_changed: Callable[[], None] | None = None,
) -> tuple[UserPreferences, MatchRun]:
    """Apply preference changes and invalidate what they affect.

    Scoring is the scheduler's job: this stales the affected matches, commits, and asks the
    caller's hook to run matching out of band. Nothing here calls a provider, so a save is
    fast and cannot fail because matching is unavailable.
    """
    prefs, changed = update_preferences(session, user_id, changes)
    if not (changed & MATCHING_RELEVANT_FIELDS):
        return prefs, MatchRun()

    session.exec(
        update(Match)
        .where(col(Match.user_id) == user_id, col(Match.status) != "dismissed")
        .values(status="stale")
    )
    session.commit()
    if on_changed is None:
        return prefs, MatchRun()
    try:
        on_changed()
    except Exception as exc:
        log.exception("waking the matcher after a preference save failed")
        return prefs, MatchRun(error=f"{type(exc).__name__}: {exc}")
    return prefs, MatchRun()
```

Add `from collections.abc import Callable` to the imports. The `deps` parameter stays for signature compatibility with existing callers and tests; mark it unused with a leading underscore only if ruff complains.

In `src/jobscout/api/routers/preferences.py`, pass the hook:

```python
@router.put("", response_model=PreferencesRead)
def put_preferences(
    payload: PreferencesUpdate,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> PreferencesRead:
    changes = payload.model_dump(exclude_unset=True)
    settings = get_settings()
    scheduler = getattr(request.app.state, "scheduler", None)
    try:
        prefs, _ = save_preferences(
            session, settings, user_id, changes, on_changed=lambda: wake_matching(scheduler)
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PreferencesRead.model_validate(prefs)
```

Add `from fastapi import Request` and `from jobscout.scheduler import wake_matching`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v && uv run mypy src`
Expected: PASS. Several existing preference tests will need the provider monkeypatching removed, since a save no longer touches one — that simplification is part of this task.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/pipeline/run.py src/jobscout/api/routers/preferences.py tests/
git commit -m "feat: hand the post-save backfill to the scheduler"
```

---

### Task 10: Lifespan wiring

**Files:**
- Modify: `src/jobscout/api/app.py`
- Test: `tests/api/test_lifespan.py`

**Interfaces:**
- Consumes: `JobScoutScheduler`.
- Produces: `app.state.scheduler` — a started `JobScoutScheduler`, or absent when disabled.

- [ ] **Step 1: Write the failing test**

Add to `tests/api/test_lifespan.py`:

```python
def test_lifespan_starts_and_stops_the_scheduler(tmp_path, monkeypatch):
    _point_settings_at(tmp_path, monkeypatch, scheduler_enabled=True)

    with TestClient(app) as client:
        scheduler = client.app.state.scheduler
        assert {job.id for job in scheduler.get_jobs()} == {"ingest", "match"}

    assert scheduler.get_jobs() == [], "shutdown must leave no jobs armed"


def test_lifespan_honours_the_disable_flag(tmp_path, monkeypatch):
    """Without this, every test that builds the app would start background threads."""
    _point_settings_at(tmp_path, monkeypatch, scheduler_enabled=False)

    with TestClient(app) as client:
        assert client.app.state.scheduler.get_jobs() == []
```

Follow the existing file's fixture for pointing `Settings` at a temp SQLite; add a `scheduler_enabled` keyword to it. The existing lifespan test must keep passing with the scheduler disabled by default in tests.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_lifespan.py -v`
Expected: FAIL with `AttributeError: 'State' object has no attribute 'scheduler'`.

- [ ] **Step 3: Write minimal implementation**

In `src/jobscout/api/app.py`:

```python
@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = get_engine(settings)
    init_db(engine)
    with Session(engine) as session:
        get_or_create_default_user(session)
    scheduler = JobScoutScheduler(engine, settings)
    scheduler.start()
    application.state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.shutdown()
```

Add `from jobscout.config import get_settings` and `from jobscout.scheduler import JobScoutScheduler`.

Set `SCHEDULER_ENABLED=false` for the test suite so no test starts threads by accident — add it to the autouse fixture in `tests/conftest.py` with `monkeypatch.setenv`, and let the two tests above override it explicitly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/api/app.py tests/api/test_lifespan.py tests/conftest.py
git commit -m "feat: start and stop the scheduler with the API"
```

---

### Task 11: `GET /runs`

**Files:**
- Create: `src/jobscout/api/routers/runs.py`
- Modify: `src/jobscout/api/schemas.py`
- Modify: `src/jobscout/api/app.py`
- Modify: `src/jobscout/pipeline/run.py`
- Test: `tests/api/test_runs.py`

**Interfaces:**
- Produces: `list_runs(session: Session, job: str | None = None, limit: int = 50) -> list[Run]` in `pipeline/run.py`; `RunRead` in `api/schemas.py`; `GET /runs?job=&limit=`.

The query lives in `pipeline`, not the router — `api` is a thin shell, and stage 2b had to extract `list_matches` for exactly this reason.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_runs.py`:

```python
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
    session.add(
        Run(job="match", ok=False, error="RuntimeError: 429", counters={"evaluated": 0})
    )
    session.commit()

    row = client.get("/runs").json()[0]

    assert (row["ok"], row["error"], row["counters"]) == (False, "RuntimeError: 429", {"evaluated": 0})


def test_runs_honours_limit(client, session):
    for _ in range(5):
        session.add(Run(job="ingest", ok=True))
    session.commit()

    assert len(client.get("/runs", params={"limit": 2}).json()) == 2


def test_runs_rejects_an_unknown_job_name(client):
    """A typo must be a 422, not an empty list that reads like 'it never ran'."""
    assert client.get("/runs", params={"job": "ingset"}).status_code == 422
```

Follow `tests/api/test_matches.py` for the `client`/`session` fixtures.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_runs.py -v`
Expected: FAIL with 404 — the route does not exist.

- [ ] **Step 3: Write minimal implementation**

In `src/jobscout/pipeline/run.py`:

```python
def list_runs(session: Session, job: str | None = None, limit: int = 50) -> list[Run]:
    """Scheduled executions, newest first."""
    statement = select(Run).order_by(desc(col(Run.started_at)))
    if job is not None:
        statement = statement.where(col(Run.job) == job)
    return list(session.exec(statement.limit(limit)).all())
```

Add `Run` to the `jobscout.models` import and `desc` to the `sqlmodel` import.

In `src/jobscout/api/schemas.py`:

```python
class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job: str
    started_at: datetime
    finished_at: datetime | None
    ok: bool
    error: str | None
    counters: dict[str, int]
```

Create `src/jobscout/api/routers/runs.py`:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from jobscout.api.deps import get_session
from jobscout.api.schemas import RunRead
from jobscout.pipeline.run import list_runs

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=list[RunRead])
def read_runs(
    session: Annotated[Session, Depends(get_session)],
    job: Annotated[str | None, Query(description="Filter by job name: ingest or match.")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RunRead]:
    """Scheduled executions, newest first. Instance-wide, not per user."""
    if job is not None and job not in RUN_JOBS:
        raise HTTPException(
            status_code=422, detail=f"unknown job {job!r}; expected one of {sorted(RUN_JOBS)}"
        )
    return [RunRead.model_validate(run) for run in list_runs(session, job=job, limit=limit)]
```

Import `HTTPException` from `fastapi` and `RUN_JOBS` from `jobscout.models`. Validating against
`RUN_JOBS` is what gives that constant a production consumer: a typo'd `?job=` must be a 422,
not an empty list that reads like "the job never ran".

Register it in `create_app` alongside the other routers.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/api/routers/runs.py src/jobscout/api/schemas.py src/jobscout/api/app.py src/jobscout/pipeline/run.py tests/api/test_runs.py
git commit -m "feat: expose the scheduled run history at GET /runs"
```

---

### Task 12: Match index, CLI tracebacks, similarity logging, docs

**Files:**
- Modify: `src/jobscout/models/match.py`
- Modify: `src/jobscout/cli.py`
- Modify: `src/jobscout/pipeline/matching.py`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/notes/2026-09-20-stage-1-followups.md`
- Test: `tests/test_match_model.py`, `tests/pipeline/test_matching.py`

**Interfaces:** no new public names.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_match_model.py`:

```python
def test_match_has_a_composite_index_for_the_hot_queries():
    """select_candidates and list_matches both filter on (user_id, status)."""
    names = {index.name for index in Match.__table__.indexes}

    assert "ix_match_user_status" in names
```

Add to `tests/pipeline/test_matching.py`:

```python
def test_run_match_logs_the_similarity_distribution(session, caplog):
    """Stage 4 calibrates SIMILARITY_THRESHOLD from this; 0.45 is currently inert."""
    user = _user_with_profile(session)
    for i in range(3):
        _add_job(session, f"j{i}")

    with caplog.at_level(logging.INFO, logger="jobscout.pipeline.matching"):
        run_match(session, _settings(), user.id, deps=_deps(CountingChatModel()))

    assert any("similarity" in record.message for record in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_match_model.py tests/pipeline/test_matching.py -v`
Expected: both new tests FAIL.

- [ ] **Step 3: Write minimal implementation**

In `src/jobscout/models/match.py`, add the index to `__table_args__`:

```python
    __table_args__ = (
        UniqueConstraint("job_id", "user_id", name="uq_match_job_user"),
        Index("ix_match_user_status", "user_id", "status"),
    )
```

Import `Index` from `sqlalchemy`.

In `src/jobscout/cli.py`:

```python
app = typer.Typer(
    help="JobScout: find jobs that match your profile.",
    no_args_is_help=True,
    # Unattended runs land in log files and Windows consoles, where a colourised
    # traceback is unreadable.
    pretty_exceptions_enable=False,
)
```

In `src/jobscout/pipeline/matching.py`, after `ranked` is built in `run_match`, log the distribution:

```python
    if ranked:
        scores = [similarity for similarity, _job in ranked]
        log.info(
            "similarity over %d candidates: min=%.3f p50=%.3f max=%.3f threshold=%.3f",
            len(scores),
            scores[-1],
            scores[len(scores) // 2],
            scores[0],
            settings.similarity_threshold,
        )
```

`ranked` is already sorted descending, so `scores[0]` is the max and `scores[-1]` the min.

Update `README.md` with a short "Running continuously" section: the scheduler runs inside `jobscout serve`, the two intervals and how to set them, `SCHEDULER_ENABLED=false` to turn it off, and `GET /runs` to see what happened. Say plainly that a preference save no longer scores anything inline — it wakes the matcher instead.

Update the "Current state" paragraph in `CLAUDE.md` to say stages 0-3 are implemented and stage 4 (`Notifier` + first channel) is next, and add a commands bullet for `GET /runs`.

In the follow-up notes, mark the stage-3 items resolved and move what remains: the `saved`/`notified` re-evaluation problem stays a stage-4 item and gets a line saying the scheduler makes it more likely; `SIMILARITY_THRESHOLD` calibration moves to stage 4 now that the distribution is logged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest && uv run mypy src && uv run ruff check . && uv run ruff format --check .`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/ tests/ README.md CLAUDE.md docs/
git commit -m "feat: index the hot match query, log similarity, document the scheduler"
```

---

### Task 13: End-to-end verification

**Files:**
- Test: `tests/test_scheduler.py`

**Interfaces:** none.

- [ ] **Step 1: Write the failing test**

Add the one test that proves the whole loop without a network, a provider, or a clock:

```python
def test_a_preference_save_leads_to_scored_matches(session, monkeypatch):
    """The stage's headline: save preferences, the scheduler wakes, matches get scored.

    Drives the real path — save_preferences -> wake -> match_job -> run_match -> Match rows
    — with fake models standing in only for the provider.
    """
    import jobscout.pipeline.matching as matching_module

    monkeypatch.setattr(matching_module, "chat_model", lambda _s: CountingChatModel())
    monkeypatch.setattr(matching_module, "embeddings", lambda _s: DeterministicFakeEmbedding(8))
    settings = _settings(embedding_dim=8, similarity_threshold=-1.0, scheduler_enabled=False)
    engine = session.get_bind()
    user = get_or_create_default_user(session)
    _add_stale_job(session, "arbeitnow", "live", days_ago=0)

    woken: list[bool] = []
    save_preferences(
        session,
        settings,
        user.id,
        {"profile_summary": "Python LLM engineer."},
        on_changed=lambda: woken.append(True),
    )
    assert woken == [True], "the save asks for a run"

    match_job(engine, settings, tick=1)

    session.expire_all()
    stored = session.exec(select(Match)).one()
    assert stored.score is not None
    run = session.exec(select(Run).where(col(Run.job) == "match")).one()
    assert (run.ok, run.counters["evaluated"]) == (True, 1)
```

Import `save_preferences` from `jobscout.pipeline.run`.

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `uv run pytest tests/test_scheduler.py::test_a_preference_save_leads_to_scored_matches -v`

This one may pass immediately if Tasks 1-12 are correct. That is fine and expected — it is a regression test over already-built behaviour, not a driver for new code. If it fails, the failure is a real integration gap between the tasks; fix it before continuing rather than adjusting the test.

- [ ] **Step 3: Full verification**

```bash
uv run pytest
uv run mypy src
uv run ruff check .
uv run ruff format --check .
uv lock --check
```

All must be clean.

- [ ] **Step 4: Manual check against the real thing**

This is the parent spec's success criterion and cannot be faked offline. With a provider key in `.env`:

```bash
INGEST_INTERVAL_MINUTES=2 MATCH_INTERVAL_MINUTES=3 uv run jobscout serve
```

Leave it running for about ten minutes, then `curl localhost:8000/runs`. Expect several `ingest` rows with counters and at least one `match` row. Then `PUT /preferences` with a changed `profile_summary` and confirm the response is immediate and a new `match` run appears within seconds.

If the Gemini free-tier quota is exhausted, run this with `SCHEDULER_ENABLED=true` but no provider key: the ingest rows still prove the scheduler works, and the match rows will show `ok=False` with the missing-provider message, which is itself the behaviour the backoff test predicts. Record which of the two you did.

- [ ] **Step 5: Commit**

```bash
git add tests/test_scheduler.py
git commit -m "test: cover the save-to-scored-match loop end to end"
```

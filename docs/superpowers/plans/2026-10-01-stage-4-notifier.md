# Stage 4 — Notifier and the first channel: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JobScout e-mails the user a daily digest of matches that cleared their threshold and have never been sent before.

**Architecture:** A `Notifier` protocol with one SMTP implementation, depending only on `models`. All queries live in `pipeline/digest.py`. A third scheduled job, `digest_job`, fires hourly and sends at most once a day per user; `notified_at` on `Match` records that the system announced a job, separately from `status`, which records what the user thinks of it.

**Tech Stack:** Python 3.12, `uv`, stdlib `smtplib` + `email.message` (no new dependency), SQLModel, APScheduler 3.x, pytest, ruff, mypy `--strict`.

**Spec:** `docs/superpowers/specs/2026-10-01-stage-4-notifier-design.md`

## Global Constraints

- Python 3.12, pinned in `.python-version`. Never the system Python; every command goes through `uv run`.
- `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy src` must all be clean before every commit. CI enforces all four.
- **No new dependency.** `smtplib` and `email.message` are stdlib. If a task seems to need a package, stop and report.
- Tests never touch the network, never send real mail, never sleep, and never depend on the wall clock.
- All timestamps are naive UTC via `jobscout.models.base.utcnow()` — **except** the `DIGEST_HOUR` comparison, which is explicitly local and aware (see Task 5).
- Operator config (env, `Settings`) is strictly separate from user preferences (DB). SMTP credentials and `DIGEST_HOUR` are operator config; the recipient address is a user preference.
- Dependency direction: `sources` (no DB) · `matching` (no HTTP) · `notifiers` (**only `models`** — no DB session, no scheduler, no HTTP) · `pipeline` (the only composer) · `api`, `cli`, `scheduler` are thin shells.
- English for code, comments and docs.
- Commit messages end with: `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## Review Focus

Five conditions the spec implies that no happy path exercises. Each has a test assigned to the task that owns the code.

1. **The send raises after some rows were selected** — expected: no `notified_at` is written at all, and the same rows are selected on the next attempt. Partial marking would silently lose matches forever. (Task 6)
2. **A second firing in the same hour, or the same day, after a successful send** — expected: no second e-mail. The guard is `max(notified_at)`, so an off-by-one in the date comparison means daily spam. (Task 6)
3. **More qualifying rows than the cap** — expected: exactly 20 sent and marked, the remainder left unmarked for the next digest (Task 5), and the body naming how many were held back (Task 4). Marking all 25 while sending 20 loses five.
4. **A user with no `notify_email`, and an instance with no SMTP configured** — expected: both are silent no-ops that do not raise, write no `Run` row, and do not stop other users from receiving theirs. (`build_notifier` returning `None` is Task 3; the job's behaviour is Task 6.)
5. **`notified_at` compared across a timezone offset and across a DST shift** — expected: "already sent today" uses the server's local calendar, so a send at 22:00 local is not read as tomorrow by a UTC+3 server, and an hour that repeats or vanishes under DST does not produce a second digest. (Task 5)

---

### Task 1: `notified_at` on `Match`

**Files:**
- Modify: `src/jobscout/models/match.py`
- Test: `tests/test_match_model.py`

**Interfaces:**
- Produces: `Match.notified_at: datetime | None`, default `None`, indexed.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_match_model.py`:

```python
def test_match_starts_unnotified():
    """`notified_at` records what the system did; `status` records what the user thinks.

    They are separate columns because staling rewrites `status` to "new", and an
    already-announced job must not return to the next digest because of that.
    """
    match = Match(job_id=1, user_id=1, similarity=0.5)

    assert match.notified_at is None


def test_notified_at_is_indexed_for_the_digest_query():
    names = {column.name for index in Match.__table__.indexes for column in index.columns}

    assert "notified_at" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_match_model.py -v`
Expected: FAIL with `AttributeError` / `TypeError` on `notified_at`.

- [ ] **Step 3: Write minimal implementation**

In `src/jobscout/models/match.py`, add the column after `llm_model`:

```python
    notified_at: datetime | None = Field(default=None, index=True)
    """When the digest announced this match. Separate from `status` on purpose: staling
    rewrites `status`, and an already-announced job must not return to the next digest."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_match_model.py -v && uv run mypy src`
Expected: PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/models/match.py tests/test_match_model.py
git commit -m "feat: record when a match was announced, separately from its status"
```

---

### Task 2: SMTP settings and the recipient preference

**Files:**
- Modify: `src/jobscout/config.py`
- Modify: `src/jobscout/models/user.py`
- Modify: `.env.example`
- Test: `tests/test_config.py`, `tests/api/test_preferences.py`

**Interfaces:**
- Produces on `Settings`: `smtp_host: str | None = None`, `smtp_port: int = 587`, `smtp_user: str | None = None`, `smtp_password: str | None = None`, `smtp_from: str | None = None`, `smtp_starttls: bool = True`, `digest_hour: int = 9`, `digest_interval_minutes: int = 60`.
- Produces on `UserPreferences`: `notify_email: str | None = None`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_notifier_settings_have_operator_defaults():
    settings = Settings(_env_file=None)

    assert settings.smtp_host is None
    assert settings.smtp_port == 587
    assert settings.smtp_starttls is True
    assert settings.digest_hour == 9
    assert settings.digest_interval_minutes == 60


def test_digest_hour_must_be_a_real_hour():
    """A typo here silently moves the daily send, so reject it loudly instead."""
    for bad in (-1, 24):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, digest_hour=bad)


def test_digest_interval_must_be_at_least_one_minute():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, digest_interval_minutes=0)
```

Add to `tests/api/test_preferences.py`:

```python
def test_notify_email_is_a_user_preference(client):
    """The recipient is per-user so the hosted demo needs no operator setup."""
    response = client.put("/preferences", json={"notify_email": "me@example.com"})

    assert response.status_code == 200
    assert client.get("/preferences").json()["notify_email"] == "me@example.com"
```

Import `pytest` and `ValidationError` from `pydantic` in `tests/test_config.py` if they are not already imported.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py tests/api/test_preferences.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'smtp_host'` and a 422 on the preferences call.

- [ ] **Step 3: Write minimal implementation**

In `src/jobscout/config.py`, add a group after the scheduler settings:

```python
    # --- Notifications (stage 4) ---
    # SMTP credentials identify who runs the instance, so they are operator config.
    # The recipient address is a user preference — that is what lets a hosted demo
    # work without the operator registering anyone.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    # Local hour (server timezone) at or after which the daily digest is sent.
    digest_hour: int = Field(default=9, ge=0, le=23)
    # The digest job polls at this interval; that is also its retry cadence, which is
    # why there is no separate retry setting.
    digest_interval_minutes: int = Field(default=60, ge=1)
```

Import `Field` from `pydantic` if `config.py` does not already import it.

In `src/jobscout/models/user.py`, add to `UserPreferences` after `min_score_to_notify`:

```python
    notify_email: str | None = None
```

In `.env.example`, add a commented block (every line commented, like the rest of the file):

```bash
# --- Notifications (stage 4) ---
# Leave SMTP_HOST unset to disable e-mail entirely; the digest job becomes a no-op.
# SMTP_HOST=smtp.example.com
# SMTP_PORT=587
# SMTP_USER=jobscout@example.com
# SMTP_PASSWORD=
# SMTP_FROM=jobscout@example.com
# SMTP_STARTTLS=true
# Local hour (this server's timezone) at or after which the daily digest goes out.
# A window missed because the process was down is still served later the same day.
# DIGEST_HOUR=9
# How often the digest job wakes to check. This is also the retry cadence after a
# failed send — there is deliberately no separate retry setting.
# DIGEST_INTERVAL_MINUTES=60
# The recipient address is NOT here: it is a per-user preference, set via PUT /preferences.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/config.py src/jobscout/models/user.py .env.example tests/
git commit -m "feat: add SMTP settings and the per-user recipient address"
```

---

### Task 3: The `Notifier` protocol and the SMTP implementation

**Files:**
- Create: `src/jobscout/notifiers/__init__.py`
- Create: `src/jobscout/notifiers/base.py`
- Create: `src/jobscout/notifiers/email.py`
- Test: `tests/notifiers/test_email.py`

**Interfaces:**
- Produces:
  - `Notifier` protocol in `base.py`: `send(self, subject: str, body: str) -> None`.
  - `SmtpNotifier(settings: Settings, recipient: str)` in `email.py`, implementing it.
  - `build_notifier(settings: Settings, recipient: str) -> Notifier | None` in `__init__.py` — `None` when `smtp_host` or `smtp_from` is unset.

This task does NOT render the digest body (Task 4) and does NOT query the database (Task 5).

- [ ] **Step 1: Write the failing test**

Create `tests/notifiers/test_email.py` (and `tests/notifiers/__init__.py` if the test layout needs it — check whether `tests/matching/` has one):

```python
from email import message_from_string

import pytest

from jobscout.config import Settings
from jobscout.notifiers import build_notifier
from jobscout.notifiers.email import SmtpNotifier


class _FakeSMTP:
    """Stands in for smtplib.SMTP. Records what would have gone over the wire."""

    instances: list["_FakeSMTP"] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host, self.port = host, port
        self.started_tls = False
        self.logged_in: tuple[str, str] | None = None
        self.sent: str | None = None
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def send_message(self, message: object) -> None:
        self.sent = str(message)


def _settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "smtp_host": "smtp.test",
        "smtp_port": 2525,
        "smtp_from": "bot@test",
        "smtp_user": "bot@test",
        "smtp_password": "secret",
    }
    base.update(kw)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset() -> None:
    _FakeSMTP.instances.clear()


def test_send_builds_a_message_to_the_recipient(monkeypatch):
    monkeypatch.setattr("jobscout.notifiers.email.smtplib.SMTP", _FakeSMTP)

    SmtpNotifier(_settings(), "me@example.com").send("JobScout: 1 new match", "the body")

    sent = message_from_string(_FakeSMTP.instances[0].sent or "")
    assert sent["To"] == "me@example.com"
    assert sent["From"] == "bot@test"
    assert sent["Subject"] == "JobScout: 1 new match"
    assert "the body" in sent.get_payload()


def test_send_uses_starttls_and_credentials_when_given(monkeypatch):
    monkeypatch.setattr("jobscout.notifiers.email.smtplib.SMTP", _FakeSMTP)

    SmtpNotifier(_settings(), "me@example.com").send("s", "b")

    smtp = _FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.test", 2525)
    assert smtp.started_tls is True
    assert smtp.logged_in == ("bot@test", "secret")


def test_send_skips_login_when_no_credentials(monkeypatch):
    """A local relay often needs neither STARTTLS nor a login."""
    monkeypatch.setattr("jobscout.notifiers.email.smtplib.SMTP", _FakeSMTP)
    settings = _settings(smtp_user=None, smtp_password=None, smtp_starttls=False)

    SmtpNotifier(settings, "me@example.com").send("s", "b")

    smtp = _FakeSMTP.instances[0]
    assert smtp.logged_in is None
    assert smtp.started_tls is False


def test_build_notifier_returns_none_without_a_host():
    assert build_notifier(_settings(smtp_host=None), "me@example.com") is None


def test_build_notifier_returns_none_without_a_sender():
    assert build_notifier(_settings(smtp_from=None), "me@example.com") is None


def test_build_notifier_returns_a_notifier_when_configured():
    assert build_notifier(_settings(), "me@example.com") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/notifiers/test_email.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.notifiers'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/jobscout/notifiers/base.py`:

```python
"""The channel contract. Implementations depend only on `models` and `config`."""

from typing import Protocol


class Notifier(Protocol):
    """Somewhere a finished message can be delivered.

    Deliberately narrow: it takes rendered text, not a list of matches, so a channel
    never has to know what a `Match` is or how a digest is composed.
    """

    def send(self, subject: str, body: str) -> None: ...
```

Create `src/jobscout/notifiers/email.py`:

```python
"""SMTP delivery. Stdlib only — `smtplib` and `email.message` need no dependency."""

import smtplib
from email.message import EmailMessage

from jobscout.config import Settings


class SmtpNotifier:
    """Sends one message per call over a fresh SMTP connection.

    A fresh connection per digest is the right trade here: the job runs at most once a
    day per user, so pooling would add state for no benefit.
    """

    def __init__(self, settings: Settings, recipient: str) -> None:
        self._settings = settings
        self._recipient = recipient

    def send(self, subject: str, body: str) -> None:
        settings = self._settings
        assert settings.smtp_host is not None, "build_notifier guarantees a host"
        assert settings.smtp_from is not None, "build_notifier guarantees a sender"

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.smtp_from
        message["To"] = self._recipient
        message.set_content(body)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_user and settings.smtp_password:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
```

Create `src/jobscout/notifiers/__init__.py`:

```python
"""Notification channels. These depend only on `config` and `models` — never on a
database session, the scheduler, or HTTP."""

from jobscout.config import Settings
from jobscout.notifiers.base import Notifier
from jobscout.notifiers.email import SmtpNotifier

__all__ = ["Notifier", "SmtpNotifier", "build_notifier"]


def build_notifier(settings: Settings, recipient: str) -> Notifier | None:
    """The configured channel, or None when this instance cannot send mail.

    None is a normal state, not an error: an operator who wants no e-mail simply leaves
    SMTP_HOST unset, and the digest job becomes a no-op.
    """
    if not settings.smtp_host or not settings.smtp_from:
        return None
    return SmtpNotifier(settings, recipient)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/notifiers/ -v && uv run mypy src`
Expected: PASS, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/notifiers tests/notifiers
git commit -m "feat: add the Notifier protocol and an SMTP implementation"
```

---

### Task 4: Rendering the digest

**Files:**
- Modify: `src/jobscout/notifiers/email.py`
- Test: `tests/notifiers/test_render.py`

**Interfaces:**
- Consumes: `Job` and `Match` from `jobscout.models`.
- Produces: `render_digest(rows: list[tuple[Match, Job]], held_back: int) -> tuple[str, str]` in `email.py`, returning `(subject, body)`.

`held_back` is the number of qualifying rows beyond the cap; the caller computes it.

- [ ] **Step 1: Write the failing test**

Create `tests/notifiers/test_render.py`:

```python
from jobscout.models import Job, Match
from jobscout.notifiers.email import render_digest


def _row(score: int, title: str, company: str = "Acme", remote: bool = True) -> tuple[Match, Job]:
    job = Job(
        source="t",
        external_id=title,
        title=title,
        company=company,
        location="Berlin",
        remote=remote,
        url=f"https://x/{title}",
        description="d",
        content_hash="h",
    )
    match = Match(
        job_id=1,
        user_id=1,
        similarity=0.8,
        score=score,
        reasoning="Strong overlap on Python.",
        missing_skills=["Kubernetes"],
    )
    return match, job


def test_subject_counts_what_is_in_this_message():
    subject, _ = render_digest([_row(88, "AI Engineer"), _row(81, "ML Engineer")], held_back=0)

    assert subject == "JobScout: 2 new matches"


def test_subject_is_singular_for_one_match():
    subject, _ = render_digest([_row(88, "AI Engineer")], held_back=0)

    assert subject == "JobScout: 1 new match"


def test_body_carries_score_title_company_reasoning_and_link():
    _, body = render_digest([_row(88, "AI Engineer")], held_back=0)

    assert "[88]" in body
    assert "AI Engineer" in body
    assert "Acme" in body
    assert "Strong overlap on Python." in body
    assert "https://x/AI Engineer" in body


def test_body_shows_remote_or_the_location():
    _, remote_body = render_digest([_row(88, "A", remote=True)], held_back=0)
    _, onsite_body = render_digest([_row(88, "B", remote=False)], held_back=0)

    assert "remote" in remote_body
    assert "Berlin" in onsite_body


def test_body_names_what_was_held_back():
    """The cap is invisible otherwise, and a silently truncated digest reads complete."""
    _, body = render_digest([_row(88, "A")], held_back=7)

    assert "7 more" in body


def test_body_says_nothing_about_held_back_when_nothing_was():
    _, body = render_digest([_row(88, "A")], held_back=0)

    assert "more" not in body.lower().split("\n")[-1]


def test_missing_skills_appear_when_present_and_are_omitted_when_not():
    match, job = _row(88, "A")
    _, with_gap = render_digest([(match, job)], held_back=0)
    match.missing_skills = []
    _, without_gap = render_digest([(match, job)], held_back=0)

    assert "Kubernetes" in with_gap
    assert "Missing" not in without_gap
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/notifiers/test_render.py -v`
Expected: FAIL with `ImportError: cannot import name 'render_digest'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/jobscout/notifiers/email.py` (import `Job` and `Match` from `jobscout.models`):

```python
def render_digest(rows: list[tuple[Match, Job]], held_back: int) -> tuple[str, str]:
    """Plain text, because it survives spam filters better and needs no template engine.

    Labels are English while `reasoning` arrives in the user's locale, so the message
    reads as mixed. That is a deliberate, visible debt: a label dictionary would start
    i18n before stage 6 decides where translations live.
    """
    plural = "match" if len(rows) == 1 else "matches"
    subject = f"JobScout: {len(rows)} new {plural}"

    blocks: list[str] = []
    for match, job in rows:
        where = "remote" if job.remote else (job.location or "location not stated")
        lines = [f"[{match.score}] {job.title} — {job.company} ({where})"]
        if match.reasoning:
            lines.append(f"     {match.reasoning}")
        if match.missing_skills:
            lines.append(f"     Missing: {', '.join(match.missing_skills)}")
        lines.append(f"     {job.url}")
        blocks.append("\n".join(lines))

    body = "\n\n".join(blocks)
    if held_back:
        body += f"\n\n{held_back} more — see /matches"
    return subject, body
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/notifiers/ -v && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/notifiers/email.py tests/notifiers/test_render.py
git commit -m "feat: render the digest as plain text"
```

---

### Task 5: Selecting and marking, plus the send-window decision

**Files:**
- Create: `src/jobscout/pipeline/digest.py`
- Test: `tests/pipeline/test_digest.py`

**Interfaces:**
- Consumes: `Job`, `Match`, `UserPreferences` from `jobscout.models`; `Settings`.
- Produces, all in `digest.py`:
  - `DIGEST_CAP = 20`
  - `select_unnotified(session, user_id, min_score, limit=DIGEST_CAP) -> tuple[list[tuple[Match, Job]], int]` — the rows to send and how many qualifying rows were left over.
  - `mark_notified(session, match_ids: list[int], now: datetime | None = None) -> None` — commits.
  - `already_sent_today(session, user_id, now_local: datetime) -> bool`
  - `is_send_window(settings, now_local: datetime) -> bool`

- [ ] **Step 1: Write the failing test**

Create `tests/pipeline/test_digest.py`:

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from jobscout.config import Settings
from jobscout.models import Job, Match
from jobscout.models.base import utcnow
from jobscout.pipeline.digest import (
    DIGEST_CAP,
    already_sent_today,
    is_send_window,
    mark_notified,
    select_unnotified,
)
from jobscout.pipeline.users import get_or_create_default_user


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _match(session: Session, user_id: int, score: int | None, **kw) -> Match:
    n = len(session.exec(select(Job)).all())
    job = Job(
        source="t",
        external_id=f"j{n}",
        title="AI Engineer",
        company="Acme",
        remote=True,
        url=f"https://x/{n}",
        description="d",
        content_hash=f"h{n}",
        is_active=kw.pop("is_active", True),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    match = Match(job_id=job.id, user_id=user_id, similarity=0.8, score=score, **kw)
    session.add(match)
    session.commit()
    session.refresh(match)
    return match


def test_selects_only_matches_above_the_threshold(session: Session):
    user = get_or_create_default_user(session)
    high = _match(session, user.id, 80)
    _match(session, user.id, 60)

    rows, held = select_unnotified(session, user.id, min_score=70)

    assert [m.id for m, _ in rows] == [high.id]
    assert held == 0


def test_never_selects_an_already_notified_match(session: Session):
    user = get_or_create_default_user(session)
    _match(session, user.id, 80, notified_at=utcnow())

    rows, _ = select_unnotified(session, user.id, min_score=70)

    assert rows == []


def test_never_selects_a_dismissed_match(session: Session):
    """The user's no survives re-scoring, exactly as it survives staling."""
    user = get_or_create_default_user(session)
    _match(session, user.id, 95, status="dismissed")

    rows, _ = select_unnotified(session, user.id, min_score=70)

    assert rows == []


def test_never_selects_a_match_whose_job_went_inactive(session: Session):
    """Announcing a dead posting is worse than announcing nothing."""
    user = get_or_create_default_user(session)
    _match(session, user.id, 95, is_active=False)

    rows, _ = select_unnotified(session, user.id, min_score=70)

    assert rows == []


def test_never_selects_an_unscored_low_row(session: Session):
    user = get_or_create_default_user(session)
    _match(session, user.id, None, status="low")

    rows, _ = select_unnotified(session, user.id, min_score=70)

    assert rows == []


def test_orders_by_score_descending(session: Session):
    user = get_or_create_default_user(session)
    for score in (72, 95, 83):
        _match(session, user.id, score)

    rows, _ = select_unnotified(session, user.id, min_score=70)

    assert [m.score for m, _ in rows] == [95, 83, 72]


def test_caps_the_batch_and_reports_what_was_held_back(session: Session):
    user = get_or_create_default_user(session)
    for _ in range(DIGEST_CAP + 5):
        _match(session, user.id, 80)

    rows, held = select_unnotified(session, user.id, min_score=70)

    assert (len(rows), held) == (DIGEST_CAP, 5)


def test_mark_notified_touches_only_the_ids_given(session: Session):
    user = get_or_create_default_user(session)
    sent = _match(session, user.id, 80)
    untouched = _match(session, user.id, 80)

    mark_notified(session, [sent.id])

    session.refresh(sent)
    session.refresh(untouched)
    assert sent.notified_at is not None
    assert untouched.notified_at is None


def test_already_sent_today_compares_local_calendar_days(session: Session):
    user = get_or_create_default_user(session)
    tz = ZoneInfo("America/Sao_Paulo")
    now_local = datetime(2026, 10, 1, 9, 0, tzinfo=tz)
    match = _match(session, user.id, 80)
    match.notified_at = now_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    session.add(match)
    session.commit()

    assert already_sent_today(session, user.id, now_local) is True
    assert already_sent_today(session, user.id, now_local + timedelta(days=1)) is False


def test_already_sent_today_survives_a_dst_shift(session: Session):
    """On the DST night the local clock repeats an hour; that must not earn a second digest.

    São Paulo's 2026 spring-forward is the fixture here; the assertion is only that two
    moments inside the same local calendar day both read as "already sent".
    """
    user = get_or_create_default_user(session)
    tz = ZoneInfo("America/Sao_Paulo")
    sent_at_local = datetime(2026, 10, 18, 1, 30, tzinfo=tz)
    match = _match(session, user.id, 80)
    match.notified_at = sent_at_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    session.add(match)
    session.commit()

    later_same_day = datetime(2026, 10, 18, 20, 0, tzinfo=tz)

    assert already_sent_today(session, user.id, later_same_day) is True


def test_send_window_opens_at_the_hour_and_stays_open(session: Session):
    """A window missed because the process was down is still served later the same day."""
    tz = ZoneInfo("America/Sao_Paulo")
    settings = _settings(digest_hour=9)

    assert is_send_window(settings, datetime(2026, 10, 1, 8, 59, tzinfo=tz)) is False
    assert is_send_window(settings, datetime(2026, 10, 1, 9, 0, tzinfo=tz)) is True
    assert is_send_window(settings, datetime(2026, 10, 1, 23, 30, tzinfo=tz)) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/pipeline/test_digest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jobscout.pipeline.digest'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/jobscout/pipeline/digest.py`:

```python
"""Choosing what goes into a digest, and recording that it went.

`notified_at` is the only thing that decides whether a match has been announced. It is
deliberately independent of `status`, which staling rewrites.
"""

from datetime import datetime

from sqlmodel import Session, col, desc, func, select

from jobscout.config import Settings
from jobscout.models import Job, Match
from jobscout.models.base import utcnow

DIGEST_CAP = 20
"""Most rows in one message. The first digest after a preference change can qualify
hundreds; an unreadable e-mail is worse than a second one tomorrow."""


def select_unnotified(
    session: Session, user_id: int, min_score: int, limit: int = DIGEST_CAP
) -> tuple[list[tuple[Match, Job]], int]:
    """The rows to announce, best first, and how many qualifying rows did not fit."""
    statement = (
        select(Match, Job)
        .join(Job, col(Match.job_id) == col(Job.id))
        .where(
            col(Match.user_id) == user_id,
            col(Match.notified_at).is_(None),
            col(Match.status) != "dismissed",
            col(Match.score).is_not(None),
            col(Match.score) >= min_score,
            col(Job.is_active).is_(True),
        )
        .order_by(desc(col(Match.score)), desc(col(Match.id)))
    )
    qualifying = list(session.exec(statement).all())
    return qualifying[:limit], max(0, len(qualifying) - limit)


def mark_notified(session: Session, match_ids: list[int], now: datetime | None = None) -> None:
    """Record the announcement. Called only after the channel accepted the message."""
    if not match_ids:
        return
    stamp = now or utcnow()
    for match in session.exec(select(Match).where(col(Match.id).in_(match_ids))).all():
        match.notified_at = stamp
        session.add(match)
    session.commit()


def already_sent_today(session: Session, user_id: int, now_local: datetime) -> bool:
    """Has this user had a digest today, in the server's local calendar?

    `notified_at` is stored naive UTC, so it is converted before the day is compared —
    otherwise a send at 22:00 local would look like tomorrow to a UTC+3 server.
    """
    latest = session.exec(
        select(func.max(col(Match.notified_at))).where(col(Match.user_id) == user_id)
    ).one()
    if latest is None:
        return False
    local = latest.replace(tzinfo=UTC).astimezone(now_local.tzinfo)
    return local.date() == now_local.date()


def is_send_window(settings: Settings, now_local: datetime) -> bool:
    """At or after DIGEST_HOUR. Deliberately not an exact-hour match: a window missed
    because the process was down is still served later the same day."""
    return now_local.hour >= settings.digest_hour
```

Add `from datetime import UTC, datetime` at the top.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/pipeline/test_digest.py -v && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/pipeline/digest.py tests/pipeline/test_digest.py
git commit -m "feat: select and mark the matches a digest announces"
```

---

### Task 6: The `digest_job` scheduled job

**Files:**
- Modify: `src/jobscout/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `select_unnotified`, `mark_notified`, `already_sent_today`, `is_send_window` from `pipeline.digest`; `build_notifier` from `notifiers`; `render_digest` from `notifiers.email`; `start_run`, `finish_run`, `should_skip_for_backoff` from this module.
- Produces: `digest_job(engine: Engine, settings: Settings, tick: int | None = None) -> None`, and `"digest"` added to `RUN_JOBS` in `models/run.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_scheduler.py`:

```python
class _RecordingNotifier:
    """Project-owned double. Records sends; optionally fails like a dead SMTP server."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[tuple[str, str]] = []

    def send(self, subject: str, body: str) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append((subject, body))


def _digest_settings(**kw) -> Settings:
    """Settings for a digest test: SMTP is configured, so `digest_job` gets past its
    "can this instance send at all" guard. The notifier itself is still faked — these
    values are never dialled."""
    kw.setdefault("smtp_host", "smtp.test")
    kw.setdefault("smtp_from", "bot@test")
    return _settings(**kw)


def _digest_fixture(session, score: int = 80):
    """A user who wants mail and one match worth announcing."""
    from jobscout.pipeline.users import update_preferences

    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"notify_email": "me@example.com"})
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
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, score=score))
    session.commit()
    return user


def test_digest_job_sends_and_marks_notified(session, monkeypatch):
    import jobscout.scheduler as scheduler_module

    user = _digest_fixture(session)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)

    digest_job(session.get_bind(), _digest_settings(digest_hour=0), tick=1)

    assert len(notifier.sent) == 1
    session.expire_all()
    assert session.exec(select(Match)).one().notified_at is not None
    run = session.exec(select(Run).where(col(Run.job) == "digest")).one()
    assert (run.ok, run.counters["sent"]) == (True, 1)


def test_digest_job_sends_once_a_day(session, monkeypatch):
    import jobscout.scheduler as scheduler_module

    _digest_fixture(session)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)
    settings = _digest_settings(digest_hour=0)

    digest_job(session.get_bind(), settings, tick=1)
    digest_job(session.get_bind(), settings, tick=2)

    assert len(notifier.sent) == 1, "a second firing the same day must not send again"


def test_a_failed_send_marks_nothing_and_retries_next_firing(session, monkeypatch):
    """The matches must survive a dead SMTP server; losing them silently is the worst case."""
    import jobscout.scheduler as scheduler_module

    _digest_fixture(session)
    failing = _RecordingNotifier(error=RuntimeError("smtp down"))
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: failing)
    settings = _digest_settings(digest_hour=0)

    digest_job(session.get_bind(), settings, tick=1)

    session.expire_all()
    assert session.exec(select(Match)).one().notified_at is None
    run = session.exec(select(Run).where(col(Run.job) == "digest")).one()
    assert run.ok is False and "smtp down" in (run.error or "")

    working = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: working)
    digest_job(session.get_bind(), settings, tick=2)

    assert len(working.sent) == 1
    session.expire_all()
    assert session.exec(select(Match)).one().notified_at is not None


def test_digest_job_is_a_no_op_before_the_send_hour(session, monkeypatch):
    import jobscout.scheduler as scheduler_module

    _digest_fixture(session)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)

    digest_job(session.get_bind(), _digest_settings(digest_hour=23), tick=1)

    assert notifier.sent == []
    assert session.exec(select(Run).where(col(Run.job) == "digest")).all() == []


def test_digest_job_writes_no_run_row_when_there_is_nothing_to_send(session, monkeypatch):
    import jobscout.scheduler as scheduler_module

    from jobscout.pipeline.users import update_preferences

    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"notify_email": "me@example.com"})
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: _RecordingNotifier())

    digest_job(session.get_bind(), _digest_settings(digest_hour=0), tick=1)

    assert session.exec(select(Run).where(col(Run.job) == "digest")).all() == []


def test_digest_job_skips_a_user_without_an_address(session, monkeypatch):
    import jobscout.scheduler as scheduler_module

    get_or_create_default_user(session)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)

    digest_job(session.get_bind(), _digest_settings(digest_hour=0), tick=1)

    assert notifier.sent == []


def test_digest_job_is_a_no_op_without_smtp(session):
    """No SMTP configured is a normal state, not an error — and writes no Run row.

    Deliberately does NOT monkeypatch `build_notifier`: the guard under test reads the
    settings directly, so faking the factory would make this test pass without ever
    exercising it.
    """
    _digest_fixture(session)

    digest_job(session.get_bind(), _settings(digest_hour=0, smtp_host=None), tick=1)

    session.expire_all()
    assert session.exec(select(Match)).one().notified_at is None
    assert session.exec(select(Run).where(col(Run.job) == "digest")).all() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scheduler.py -v -k digest`
Expected: FAIL with `ImportError: cannot import name 'digest_job'`.

- [ ] **Step 3: Write minimal implementation**

In `src/jobscout/models/run.py`, widen the constant:

```python
RUN_JOBS: frozenset[str] = frozenset({"ingest", "match", "digest"})
```

Add to `src/jobscout/scheduler.py`:

```python
def digest_job(engine: Engine, settings: Settings, tick: int | None = None) -> None:
    """Send each user their daily digest, at most once a day.

    Runs hourly rather than daily so a failed send is retried within the hour instead of
    waiting until tomorrow. The "did I already send" decision comes from `notified_at`,
    which is durable, so a restart cannot cause a second e-mail.
    """
    try:
        _digest(engine, settings, tick)
    except Exception:
        log.exception("digest job failed")


def _digest(engine: Engine, settings: Settings, tick: int | None) -> None:
    with Session(engine) as session:
        if tick is not None and should_skip_for_backoff(session, settings, "digest", tick):
            log.info("digest tick %s skipped by backoff", tick)
            return
        # Local and aware on purpose: DIGEST_HOUR is what the operator reads on their
        # own clock. This is the one place the project's naive-UTC rule must not apply.
        now_local = datetime.now().astimezone()
        if not is_send_window(settings, now_local):
            return

        # Decided before any Run row is opened: an instance that cannot send mail is a
        # no-op, not an execution. Writing a row here would put a daily "no SMTP" line in
        # /runs forever for every operator who does not want e-mail.
        if not settings.smtp_host or not settings.smtp_from:
            log.info("no SMTP configured; digest is a no-op")
            return

        users = list(session.exec(select(User)).all())
        pending: list[tuple[int, str, list[int], str, str]] = []
        for user in users:
            if user.id is None:
                continue
            prefs = get_preferences(session, user.id)
            if not prefs.notify_email:
                continue
            if already_sent_today(session, user.id, now_local):
                continue
            rows, held_back = select_unnotified(session, user.id, prefs.min_score_to_notify)
            if not rows:
                continue
            subject, body = render_digest(rows, held_back)
            ids = [m.id for m, _ in rows if m.id is not None]
            pending.append((user.id, prefs.notify_email, ids, subject, body))

        if not pending:
            return

        run = start_run(session, settings, "digest")
        counters = {"users": 0, "sent": 0, "held_back": 0}
        errors: list[str] = []
        for user_id, address, ids, subject, body in pending:
            notifier = build_notifier(settings, address)
            assert notifier is not None, "the no-SMTP case returned before the run opened"
            try:
                notifier.send(subject, body)
            except Exception as exc:
                errors.append(f"user {user_id}: {type(exc).__name__}: {exc}")
                continue
            mark_notified(session, ids)
            counters["users"] += 1
            counters["sent"] += len(ids)
        finish_run(
            session, run, ok=not errors, counters=counters, error="; ".join(errors) or None
        )
```

Add the imports this needs: `datetime` from `datetime`, `User` and `get_preferences` from their modules, and the four digest helpers plus `build_notifier` and `render_digest`.

Register the job in `JobScoutScheduler.start`, following the two existing `add_job` calls:

```python
        self._scheduler.add_job(
            self._run_digest_tick,
            "interval",
            minutes=self._settings.digest_interval_minutes,
            id="digest",
            max_instances=1,
            coalesce=True,
            jitter=jitter,
            replace_existing=True,
        )
```

with a `_run_digest_tick` that increments its own counter, mirroring `_run_match_tick`:

```python
    def _run_digest_tick(self) -> None:
        self._digest_tick += 1
        digest_job(self._engine, self._settings, tick=self._digest_tick)
```

and `self._digest_tick = 0` in `__init__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -v && uv run mypy src && uv run ruff check .`
Expected: PASS. The lifespan tests that assert the registered job ids will need `"digest"` added — that update is part of this task.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/scheduler.py src/jobscout/models/run.py tests/
git commit -m "feat: send a daily digest from the scheduler"
```

---

### Task 7: Documentation and the end-to-end check

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-09-19-jobscout-design.md`
- Modify: `docs/superpowers/notes/2026-09-20-stage-1-followups.md`
- Test: `tests/test_scheduler.py`

**Interfaces:** no new public names.

- [ ] **Step 1: Write the failing test**

Add the one test that proves the whole loop, in `tests/test_scheduler.py`:

```python
def test_a_scored_match_reaches_a_digest_and_is_never_sent_twice(session, monkeypatch):
    """Stage 4's headline: score -> digest -> marked -> never again.

    Drives the real `digest_job`, with a double standing in only for SMTP.
    """
    import jobscout.scheduler as scheduler_module

    user = _digest_fixture(session, score=88)
    notifier = _RecordingNotifier()
    monkeypatch.setattr(scheduler_module, "build_notifier", lambda *_a: notifier)
    settings = _digest_settings(digest_hour=0)

    digest_job(session.get_bind(), settings, tick=1)

    subject, body = notifier.sent[0]
    assert subject == "JobScout: 1 new match"
    assert "[88] AI Engineer — Acme" in body

    # A later day must not re-announce it, even though staling would reset `status`.
    session.expire_all()
    match = session.exec(select(Match)).one()
    match.status = "stale"
    match.notified_at = utcnow() - timedelta(days=2)
    session.add(match)
    session.commit()

    digest_job(session.get_bind(), settings, tick=2)

    assert len(notifier.sent) == 1, "notified_at, not status, decides"
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `uv run pytest tests/test_scheduler.py -v -k reaches_a_digest`

It may pass immediately — Tasks 1-6 built everything it exercises, so it is a regression test over working behaviour. **If it fails, that is a real integration gap: fix the code, not the test.**

- [ ] **Step 3: Update the documentation**

`README.md` — add a "Notifications" section: set `SMTP_*` and `DIGEST_HOUR` in the environment, set `notify_email` via `PUT /preferences`, one digest a day at or after that local hour, at most 20 matches per message, nothing sent when nothing clears `min_score_to_notify`. Say plainly that leaving `SMTP_HOST` unset disables e-mail and everything else still works.

`CLAUDE.md` — the "Current state" paragraph becomes stages 0 through 4 implemented, next is stage 5 (more sources). Add `notifiers` to the dependency-direction sentence, between `matching` and `pipeline`.

The **live parent spec** — §4 gains `notifiers/email.py`, `pipeline/digest.py` and the eight settings; §5 step 4 is replaced by the digest rule; §7 gains `Match.notified_at` and `UserPreferences.notify_email`. The stage-3 spec and anything under `plans/` are history: do not touch them.

The follow-up notes — mark the stage-4 item resolved, saying `notified_at` separated the system's record from the user's status, and carry anything still open to its stage.

- [ ] **Step 4: Full verification**

```bash
uv run pytest
uv run mypy src
uv run ruff check .
uv run ruff format --check .
uv lock --check
```

All must be clean.

- [ ] **Step 5: Manual check against a real SMTP server**

This is the parent spec's success criterion and cannot be faked offline. With real SMTP credentials in `.env` and `notify_email` set:

```bash
DIGEST_HOUR=0 DIGEST_INTERVAL_MINUTES=1 uv run jobscout serve
```

Wait for a digest, then `curl localhost:8000/runs?job=digest`.

**Expect this to send nothing.** With `min_score_to_notify` at 70 and the current corpus, the LLM scores almost everything between 0 and 35. If no e-mail arrives, confirm it is for that reason — check `/matches` for the highest score on record — and **record that as a finding about matching quality, not a failure of this stage.** Do not lower the threshold to manufacture a send. To exercise the path end to end anyway, temporarily set `min_score_to_notify` low via `PUT /preferences` (a user preference, not a shipped default), confirm the e-mail arrives, then restore it. Report which of the two you did.

- [ ] **Step 6: Commit**

```bash
git add README.md CLAUDE.md docs/ tests/
git commit -m "docs: document the digest and record the stage 4 outcome"
```

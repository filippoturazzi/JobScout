# JobScout Stage 2a: Groundwork for Matching — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape the stage-1 pipeline so stage 2b can add the matching graph on stable contracts: global ingest, metadata refresh with `created_ids`/`changed_ids`, one engine seam with a tested lifespan, token-based filters, word-safe `html_to_text`, mypy in CI, and one source of truth for non-nullable preference fields.

**Architecture:** No new subsystems. Seven focused changes to existing modules (`db`, `pipeline/ingest`, `pipeline/run`, `pipeline/filters`, `sources/text`, `api/schemas`, `pipeline/users`) plus `cli.py`/`api/app.py` call-site updates and tooling. Dependency rules from the parent spec are unchanged.

**Tech Stack:** Python 3.12, uv, SQLModel, FastAPI, Typer, pytest, respx, ruff, mypy (new, dev only).

**Spec:** `docs/superpowers/specs/2026-09-21-stage-2a-groundwork-design.md` (amends `docs/superpowers/specs/2026-09-19-jobscout-design.md` §4, §5, §8)

## Global Constraints

- Always `uv run ...` (Python 3.12 pinned); never the system Python. `uv` lives at `$env:USERPROFILE\.local\bin\uv.exe` on the dev machine if not on PATH.
- Tests never touch the network; DB is in-memory or `tmp_path` SQLite. Real-API tests stay behind `-m integration`.
- All datetimes naive UTC (`jobscout.models.base.utcnow()`).
- Dependency direction: `sources` → no DB; `pipeline` is the only composer; `api`/`cli` thin shells over `pipeline`; `api`/`pipeline` may import `models`.
- `uv run ruff check .` and `uv run ruff format --check .` clean before every commit; from Task 7 on, `uv run mypy src` clean too.
- Every commit ends with the trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` (second `-m`), conventional prefixes (`feat:`, `fix:`, `refactor:`, `test:`, `chore:`, `ci:`, `docs:`).
- Test output pristine (no warnings). Existing tests are kept unless the plan says to change or delete them.
- Baseline: `main` at `0a81260`, 79 unit tests passing.

---

## File Structure

```
src/jobscout/db.py                 get_engine(settings=None), reset_engines(); _engines dict   [Task 1]
src/jobscout/cli.py                _session() via get_engine; fetch without user                [Tasks 1, 2]
src/jobscout/api/app.py            lifespan unchanged in shape (uses get_engine())              [Task 1 test only]
src/jobscout/pipeline/run.py       run_ingest(session, settings, sources=None); no build_query  [Task 2]
src/jobscout/pipeline/ingest.py    metadata refresh; UpsertStats/IngestResult ids               [Task 3]
src/jobscout/pipeline/filters.py   tokenize(), _contains_sequence(), rewritten rules            [Task 4]
src/jobscout/sources/text.py       block-aware joining                                          [Task 5]
src/jobscout/models/user.py        PROTECTED_PREFERENCE_FIELDS, non_nullable_preference_fields() [Task 6]
src/jobscout/api/schemas.py        validator fields derived                                      [Task 6]
src/jobscout/pipeline/users.py     uses the shared sets                                          [Task 6]
pyproject.toml, .github/workflows/ci.yml, README.md, CLAUDE.md   mypy                            [Task 7]
tests/conftest.py                  autouse reset fixture                                         [Task 1]
tests/test_db.py                   new                                                           [Task 1]
tests/api/test_lifespan.py         new                                                           [Task 1]
tests/pipeline/test_run.py, tests/test_cli.py, tests/pipeline/test_ingest.py,
tests/pipeline/test_filters.py, tests/sources/test_text.py, tests/pipeline/test_users.py,
tests/api/test_preferences.py      updated per task
```

---

### Task 1: Engine seam + lifespan test

**Files:**
- Modify: `src/jobscout/db.py`
- Modify: `src/jobscout/cli.py:20-23` (`_session`)
- Modify: `tests/conftest.py`
- Create: `tests/test_db.py`, `tests/api/test_lifespan.py`

**Interfaces:**
- Consumes: `Settings`, `get_settings()` (`jobscout.config`); `create_engine_from_url`, `init_db` (existing).
- Produces: `jobscout.db.get_engine(settings: Settings | None = None) -> Engine` (one cached engine per `database_url`), `jobscout.db.reset_engines() -> None`. `_engines: dict[str, Engine]` is private.

- [ ] **Step 1: Write the failing tests**

`tests/test_db.py`:
```python
from jobscout.config import Settings
from jobscout.db import get_engine, reset_engines


def _settings(url: str) -> Settings:
    return Settings(_env_file=None, database_url=url)


def test_same_url_returns_same_engine(tmp_path):
    s = _settings(f"sqlite:///{tmp_path / 'a.db'}")
    assert get_engine(s) is get_engine(s)


def test_different_urls_return_different_engines(tmp_path):
    a = get_engine(_settings(f"sqlite:///{tmp_path / 'a.db'}"))
    b = get_engine(_settings(f"sqlite:///{tmp_path / 'b.db'}"))
    assert a is not b


def test_reset_engines_yields_fresh_instance(tmp_path):
    s = _settings(f"sqlite:///{tmp_path / 'a.db'}")
    before = get_engine(s)
    reset_engines()
    assert get_engine(s) is not before


def test_get_engine_defaults_to_settings(monkeypatch, tmp_path):
    import jobscout.db as db

    monkeypatch.setattr(db, "get_settings", lambda: _settings(f"sqlite:///{tmp_path / 'd.db'}"))
    assert str(get_engine().url).endswith("d.db")
```

`tests/api/test_lifespan.py`:
```python
from fastapi.testclient import TestClient

import jobscout.db as db
from jobscout.api.app import app
from jobscout.config import Settings


def test_lifespan_initializes_db_and_default_user(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setattr(db, "get_settings", lambda: settings)
    assert not app.dependency_overrides, "this test must exercise the real dependency path"

    with TestClient(app) as client:
        response = client.get("/preferences")

    assert response.status_code == 200
    assert response.json()["titles"] == []
```

Append to `tests/conftest.py`:
```python
@pytest.fixture(autouse=True)
def _isolate_engines():
    """Every test starts and ends without cached engines or cached settings."""
    from jobscout.config import get_settings
    from jobscout.db import reset_engines

    reset_engines()
    get_settings.cache_clear()
    yield
    reset_engines()
    get_settings.cache_clear()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_db.py tests/api/test_lifespan.py -v`
Expected: FAIL with `ImportError: cannot import name 'reset_engines'` (and `get_engine()` takes no arguments).

- [ ] **Step 3: Implement `db.py`**

Replace the `get_engine` block (lines 27-29) with:
```python
_engines: dict[str, Engine] = {}


def get_engine(settings: Settings | None = None) -> Engine:
    """One engine per DATABASE_URL, shared by the CLI, the API lifespan and (stage 3) the scheduler."""
    url = (settings or get_settings()).database_url
    if url not in _engines:
        _engines[url] = create_engine_from_url(url)
    return _engines[url]


def reset_engines() -> None:
    """Dispose and forget every cached engine (tests, or after changing settings)."""
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()
```
Update imports: remove `from functools import lru_cache`; change `from jobscout.config import get_settings` to `from jobscout.config import Settings, get_settings`.

- [ ] **Step 4: Point the CLI at the seam**

In `src/jobscout/cli.py` replace `_session`:
```python
def _session() -> Session:
    engine = get_engine(get_settings())
    init_db(engine)
    return Session(engine)
```
and change the import `from jobscout.db import create_engine_from_url, init_db` to `from jobscout.db import get_engine, init_db`.

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_db.py tests/api/test_lifespan.py tests/test_cli.py tests/api -v`
Expected: all pass. Then `uv run pytest -q` → 84 passed, no warnings.

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/db.py src/jobscout/cli.py tests/conftest.py tests/test_db.py tests/api/test_lifespan.py
git commit -m "refactor: cache one engine per DATABASE_URL and test the API lifespan" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Global ingest

**Files:**
- Modify: `src/jobscout/pipeline/run.py`
- Modify: `src/jobscout/cli.py` (`fetch`)
- Modify: `tests/pipeline/test_run.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `ingest(session, sources, query, now=None)` (existing), `build_sources(settings)`.
- Produces: `run_ingest(session: Session, settings: Settings, sources: list[JobSource] | None = None) -> list[IngestResult]`. `build_query` is deleted.

- [ ] **Step 1: Update the tests first**

In `tests/pipeline/test_run.py`: delete `test_build_query_from_preferences`; remove `build_query` and `UserPreferences` from the imports if no longer used; replace `test_run_ingest_uses_prefs_and_given_sources` with:
```python
def test_run_ingest_is_global_and_uses_given_sources(session):
    src = FakeSource([raw("a", "AI Engineer")])
    results = run_ingest(session, Settings(_env_file=None), sources=[src])
    assert src.last_query == SearchQuery()
    assert results[0].created == 1


def test_run_ingest_does_not_need_a_user(session):
    from sqlmodel import select

    from jobscout.models import User

    run_ingest(session, Settings(_env_file=None), sources=[FakeSource([])])
    assert session.exec(select(User)).all() == []
```

In `tests/test_cli.py::test_fetch_then_jobs`, after the `fetch` invocation and before invoking `jobs`, add:
```python
    from sqlmodel import Session, select

    from jobscout.db import get_engine
    from jobscout.models import User

    with Session(get_engine(_settings(tmp_path))) as s:
        assert s.exec(select(User)).all() == [], "fetch must not bootstrap a user"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pipeline/test_run.py tests/test_cli.py -v`
Expected: FAIL — `run_ingest() missing 1 required positional argument: 'user_id'` and the CLI test's "must not bootstrap a user" assertion.

- [ ] **Step 3: Implement**

`src/jobscout/pipeline/run.py`: delete `build_query`; replace `run_ingest`:
```python
def run_ingest(
    session: Session,
    settings: Settings,
    sources: list[JobSource] | None = None,
) -> list[IngestResult]:
    """Instance-global collection. Sources return everything; user filtering happens later."""
    sources = sources if sources is not None else build_sources(settings)
    return ingest(session, sources, SearchQuery())
```
Remove now-unused imports (`UserPreferences`, `get_preferences` stays because `list_jobs` uses it).

`src/jobscout/cli.py::fetch`: drop the user lookup:
```python
@app.command()
def fetch() -> None:
    """Fetch jobs from all enabled sources into the database."""
    settings = get_settings()
    with _session() as session:
        try:
            results = run_ingest(session, settings)
        except ValueError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=2) from exc
```
(keep the result-printing loop as is). `get_or_create_default_user` is still imported for `jobs`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -q`
Expected: 85 passed (84 − 1 deleted + 2 new), no warnings.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/pipeline/run.py src/jobscout/cli.py tests/pipeline/test_run.py tests/test_cli.py
git commit -m "refactor: make ingest instance-global; drop per-user SearchQuery until stage 5" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Upsert refreshes metadata and reports ids

**Files:**
- Modify: `src/jobscout/pipeline/ingest.py`
- Modify: `tests/pipeline/test_ingest.py`

**Interfaces:**
- Produces: `UpsertStats(created, updated, changed, created_ids: list[int], changed_ids: list[int])`; `IngestResult(source, fetched, created, updated, changed, created_ids, changed_ids, error)`. Semantics per spec §5.1.

- [ ] **Step 1: Write the failing tests** (append to `tests/pipeline/test_ingest.py`; `raw()` accepts `**kw`)

```python
def test_metadata_is_refreshed_on_every_sighting(session):
    upsert_jobs(session, [raw("j1", location="Berlin", remote=True, tags=["python"])], now=T0)
    j1 = session.exec(select(Job)).one()
    j1.embedding = b"\x01"
    session.add(j1)
    session.commit()

    stats = upsert_jobs(
        session,
        [
            raw(
                "j1",
                location="Munich",
                remote=False,
                tags=["python", "llm"],
                salary_min=60000,
                salary_currency="EUR",
            )
        ],
        now=T0 + timedelta(hours=1),
    )
    session.refresh(j1)
    assert (stats.created, stats.updated, stats.changed) == (0, 1, 0)
    assert j1.location == "Munich" and j1.remote is False
    assert j1.tags == ["python", "llm"] and j1.salary_min == 60000
    assert j1.embedding == b"\x01", "same text: embedding must be kept"
    assert j1.content_hash == content_hash("AI Engineer", "Build agents.")


def test_stats_carry_created_and_changed_ids(session):
    first = upsert_jobs(session, [raw("a"), raw("b")], now=T0)
    ids = {j.external_id: j.id for j in session.exec(select(Job)).all()}
    assert sorted(first.created_ids) == sorted([ids["a"], ids["b"]])
    assert first.changed_ids == []

    second = upsert_jobs(
        session, [raw("a"), raw("b", description="new text"), raw("c")], now=T0
    )
    ids = {j.external_id: j.id for j in session.exec(select(Job)).all()}
    assert second.created_ids == [ids["c"]]
    assert second.changed_ids == [ids["b"]]

    third = upsert_jobs(session, [raw("a"), raw("b", description="new text"), raw("c")], now=T0)
    assert (third.created_ids, third.changed_ids) == ([], [])


def test_ingest_result_exposes_ids(session):
    results = ingest(session, [FakeSource("ok", [raw("x", source="ok")])], SearchQuery(), now=T0)
    job_id = session.exec(select(Job)).one().id
    assert results[0].created_ids == [job_id]
    assert results[0].changed_ids == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pipeline/test_ingest.py -v`
Expected: the three new tests FAIL (`location` still "Berlin"; `UpsertStats` has no `created_ids`).

- [ ] **Step 3: Implement**

In `src/jobscout/pipeline/ingest.py`:

```python
from dataclasses import dataclass, field

_METADATA_FIELDS = (
    "company",
    "location",
    "remote",
    "url",
    "salary_min",
    "salary_max",
    "salary_currency",
    "tags",
    "posted_at",
    "raw",
)


@dataclass
class UpsertStats:
    created: int = 0
    updated: int = 0
    changed: int = 0
    created_ids: list[int] = field(default_factory=list)
    changed_ids: list[int] = field(default_factory=list)


@dataclass
class IngestResult:
    source: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    changed: int = 0
    created_ids: list[int] = field(default_factory=list)
    changed_ids: list[int] = field(default_factory=list)
    error: str | None = None
```

Replace the per-key loop and commit in `upsert_jobs` with:
```python
    created_jobs: list[Job] = []
    changed_jobs: list[Job] = []
    for key, raw in by_key.items():
        new_hash = content_hash(raw.title, raw.description)
        job = existing.get(key)
        if job is None:
            job = Job(
                **raw.model_dump(),
                content_hash=new_hash,
                first_seen_at=now,
                last_seen_at=now,
                is_active=True,
            )
            session.add(job)
            created_jobs.append(job)
            stats.created += 1
            continue

        # Every sighting: liveness + metadata refresh.
        job.last_seen_at = now
        job.is_active = True
        for name in _METADATA_FIELDS:
            setattr(job, name, getattr(raw, name))
        # Only a text change invalidates what was derived from the text.
        if job.content_hash != new_hash:
            job.title = raw.title
            job.description = raw.description
            job.content_hash = new_hash
            job.embedding = None
            changed_jobs.append(job)
            stats.changed += 1
        else:
            stats.updated += 1
        session.add(job)

    session.flush()  # assigns ids for the new rows
    stats.created_ids = [job.id for job in created_jobs if job.id is not None]
    stats.changed_ids = [job.id for job in changed_jobs if job.id is not None]
    session.commit()
    return stats
```
Update the module docstring's second sentence to: "Every sighting refreshes metadata and `last_seen_at`; only a title/description change clears the cached embedding (stage 2b also marks matches stale) and keeps `first_seen_at`."

In `ingest()`, replace the tuple assignment with:
```python
        result.created, result.updated, result.changed = (
            stats.created,
            stats.updated,
            stats.changed,
        )
        result.created_ids, result.changed_ids = stats.created_ids, stats.changed_ids
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/pipeline -v` then `uv run pytest -q`
Expected: 88 passed, no warnings. `test_changed_content_updates_text_and_clears_embedding` and `test_rerun_same_data_only_touches_last_seen` must still pass unchanged.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/pipeline/ingest.py tests/pipeline/test_ingest.py
git commit -m "feat: refresh job metadata on every sighting and report created/changed ids" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Token-based filters

**Files:**
- Modify: `src/jobscout/pipeline/filters.py`
- Modify: `tests/pipeline/test_filters.py`

**Interfaces:**
- Produces: `tokenize(text: str) -> list[str]` (public; stage 2b may reuse), `job_matches_preferences`, `filter_jobs` (unchanged signatures).

- [ ] **Step 1: Write the failing tests** (append to `tests/pipeline/test_filters.py`)

```python
from jobscout.pipeline.filters import tokenize


def test_tokenize_preserves_order_and_handles_tech_tokens():
    assert tokenize("Senior .NET / C++ Engineer.") == ["senior", ".net", "c++", "engineer"]
    assert tokenize("") == []


def test_exclusions_match_whole_tokens_not_substrings():
    p = prefs(excluded_keywords=["ai"])
    assert job_matches_preferences(job(title="Maintenance Engineer"), p)
    assert not job_matches_preferences(job(title="AI Engineer"), p)
    assert not job_matches_preferences(job(title="Engineer", tags=["AI"]), p)


def test_exclusions_match_contiguous_phrases():
    p = prefs(excluded_keywords=["machine learning"])
    assert not job_matches_preferences(job(title="Machine Learning Engineer"), p)
    assert job_matches_preferences(job(title="Learning Platform Machine Operator"), p)
    assert not job_matches_preferences(job(title="Engineer", tags=["Machine Learning"]), p)


def test_regions_match_location_segments_not_substrings():
    p = prefs(regions=["US"])
    assert not job_matches_preferences(job(location="Sydney, Australia"), p)
    assert job_matches_preferences(job(location="Austin, TX, US"), p)

    p = prefs(regions=["Germany", "New York"])
    assert job_matches_preferences(job(location="Berlin, Berlin, Germany"), p)
    assert job_matches_preferences(job(location="New York City, NY"), p)
    assert not job_matches_preferences(job(location="Paris, France"), p)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pipeline/test_filters.py -v`
Expected: FAIL — `ImportError: cannot import name 'tokenize'`.

- [ ] **Step 3: Implement**

Replace `src/jobscout/pipeline/filters.py` body (keep the module docstring):
```python
import re
from collections.abc import Iterable

from jobscout.models import Job, UserPreferences

_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens in order; trailing periods dropped, leading dots kept (".net")."""
    tokens = (token.rstrip(".") for token in _TOKEN_RE.findall(text.lower()))
    return [token for token in tokens if token]


def _contains_sequence(haystack: list[str], needle: list[str]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(haystack[i : i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1))


def _passes_exclusions(job: Job, prefs: UserPreferences) -> bool:
    title_tokens = tokenize(job.title)
    tag_tokens = [tokenize(tag) for tag in job.tags]
    for keyword in prefs.excluded_keywords:
        needle = tokenize(keyword)
        if not needle:
            continue
        if _contains_sequence(title_tokens, needle) or needle in tag_tokens:
            return False
    return True


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
    segments = [tokenize(segment) for segment in (job.location or "").split(",")]
    for region in prefs.regions:
        needle = tokenize(region)
        if needle and any(_contains_sequence(segment, needle) for segment in segments):
            return True
    return False


def _passes_titles(job: Job, prefs: UserPreferences) -> bool:
    if not prefs.titles:
        return True
    title_words = set(tokenize(job.title))
    return any(set(tokenize(t)) and set(tokenize(t)) <= title_words for t in prefs.titles)


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
Expected: all pass, including the seven pre-existing tests (regression). Note `test_regions_apply_to_onsite_only` uses `location="lisbon, portugal"` with `regions=["Portugal"]` → segment `["portugal"]` equals needle → passes.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/pipeline/filters.py tests/pipeline/test_filters.py
git commit -m "fix: match exclusions and regions on tokens and location segments" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Word-safe `html_to_text`

**Files:**
- Modify: `src/jobscout/sources/text.py`
- Modify: `tests/sources/test_text.py`

**Interfaces:**
- Produces: `html_to_text(value: str) -> str` (unchanged signature).

- [ ] **Step 1: Write the failing tests** (append to `tests/sources/test_text.py`)

```python
def test_inline_tags_do_not_split_words():
    assert html_to_text("Java<b>Script</b> and Type<i>Script</i>") == "JavaScript and TypeScript"


def test_block_tags_separate_text():
    assert html_to_text("<p>a</p><p>b</p>") == "a b"
    assert html_to_text("<ul><li>x</li><li>y</li></ul>") == "x y"
    assert html_to_text("a<br>b<br/>c") == "a b c"
    assert html_to_text("<h2>Title</h2>Body") == "Title Body"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/sources/test_text.py -v`
Expected: `test_inline_tags_do_not_split_words` FAILS (`"Java Script and Type Script"`).

- [ ] **Step 3: Implement**

In `src/jobscout/sources/text.py`, add after `_SKIPPED_ELEMENTS`:
```python
_BLOCK_ELEMENTS = {
    "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "table", "section", "article", "header", "footer", "blockquote", "pre", "hr",
}
```
Change `_TextExtractor` handlers:
```python
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_ELEMENTS:
            self._skip_depth += 1
        elif tag in _BLOCK_ELEMENTS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_ELEMENTS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_ELEMENTS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_ELEMENTS:
            self.parts.append("\n")
```
and in `html_to_text` change `" ".join(parser.parts)` to `"".join(parser.parts)`. Update the class docstring to "Collects text nodes, skipping script/style content; block-level tags become line breaks."

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/sources -v`
Expected: all pass, including the Arbeitnow fixture expectations (`"Join the AI of Manufacturing PartSpace builds Document AI for CAD/CAM."`, `"Brief info about Vinted Our marketplace."`) and the contract test.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/sources/text.py tests/sources/test_text.py
git commit -m "fix: keep words intact across inline tags in html_to_text" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: One source of truth for non-nullable preference fields

**Files:**
- Modify: `src/jobscout/models/user.py`
- Modify: `src/jobscout/api/schemas.py`
- Modify: `src/jobscout/pipeline/users.py`
- Modify: `tests/pipeline/test_users.py`, `tests/api/test_preferences.py`

**Interfaces:**
- Produces (in `jobscout.models.user`): `PROTECTED_PREFERENCE_FIELDS: frozenset[str]` and `non_nullable_preference_fields() -> frozenset[str]` (non-nullable columns of `user_preferences` minus protected).

- [ ] **Step 1: Write the failing tests**

Append to `tests/pipeline/test_users.py`:
```python
from jobscout.models.user import PROTECTED_PREFERENCE_FIELDS, non_nullable_preference_fields


def test_non_nullable_fields_are_derived_from_the_table():
    assert non_nullable_preference_fields() == frozenset(
        {
            "titles",
            "seniority",
            "work_modes",
            "regions",
            "required_skills",
            "nice_to_have_skills",
            "excluded_keywords",
            "profile_summary",
            "min_score_to_notify",
        }
    )
    assert PROTECTED_PREFERENCE_FIELDS == frozenset(
        {"id", "user_id", "created_at", "updated_at", "profile_embedding"}
    )
```

Append to `tests/api/test_preferences.py`:
```python
def test_update_schema_rejects_null_for_every_non_nullable_field(client):
    from jobscout.models.user import non_nullable_preference_fields

    for name in sorted(non_nullable_preference_fields()):
        r = client.put("/preferences", json={name: None})
        assert r.status_code == 422, name
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pipeline/test_users.py tests/api/test_preferences.py -v`
Expected: FAIL — `ImportError: cannot import name 'PROTECTED_PREFERENCE_FIELDS'`.

- [ ] **Step 3: Implement**

`src/jobscout/models/user.py` — append after the `UserPreferences` class:
```python
PROTECTED_PREFERENCE_FIELDS: frozenset[str] = frozenset(
    {"id", "user_id", "created_at", "updated_at", "profile_embedding"}
)


def non_nullable_preference_fields() -> frozenset[str]:
    """User-editable preference columns that must never be set to NULL."""
    table = UserPreferences.__table__  # Task 7 adds a narrow type-ignore here only if mypy asks
    return frozenset(
        column.name
        for column in table.columns
        if not column.nullable and column.name not in PROTECTED_PREFERENCE_FIELDS
    )
```
(Also export both from `src/jobscout/models/__init__.py`: add them to the import and `__all__`.)

`src/jobscout/pipeline/users.py`: replace `_PROTECTED_FIELDS` usage:
```python
from jobscout.models import User, UserPreferences
from jobscout.models.user import PROTECTED_PREFERENCE_FIELDS, non_nullable_preference_fields
```
delete the `_PROTECTED_FIELDS = {...}` line; in `update_preferences`:
```python
    allowed = set(UserPreferences.model_fields) - PROTECTED_PREFERENCE_FIELDS
    ...
    non_nullable = non_nullable_preference_fields()
    non_nullable_nulls = sorted(
        field for field, value in changes.items() if value is None and field in non_nullable
    )
```

`src/jobscout/api/schemas.py`: replace the hardcoded validator field list:
```python
from jobscout.models.user import non_nullable_preference_fields
...
    @field_validator(*sorted(non_nullable_preference_fields()), mode="before")
    @classmethod
    def _reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("field cannot be null")
        return value
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -q`
Expected: 96 passed, no warnings (all existing null/protected tests still pass).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . ; uv run ruff format .`
```powershell
git add src/jobscout/models/user.py src/jobscout/models/__init__.py src/jobscout/pipeline/users.py src/jobscout/api/schemas.py tests/pipeline/test_users.py tests/api/test_preferences.py
git commit -m "refactor: derive non-nullable preference fields from the table in both layers" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: mypy --strict on `src/` in CI

**Files:**
- Modify: `pyproject.toml`, `.github/workflows/ci.yml`, `README.md`, `CLAUDE.md`
- Modify: any `src/` file mypy flags (targeted fixes only)

**Interfaces:** none; tooling.

- [ ] **Step 1: Add mypy and its config**

`pyproject.toml` — in `[dependency-groups] dev` add `"mypy>=1.13"`; append:
```toml
[tool.mypy]
files = ["src"]
strict = true
plugins = ["pydantic.mypy"]
warn_unreachable = true

[[tool.mypy.overrides]]
module = ["uvicorn.*"]
ignore_missing_imports = true
```
Run: `uv sync --all-groups` then `uv run mypy src`.

- [ ] **Step 2: Fix every reported error with the narrowest change**

Rules: prefer adding a precise annotation or a `cast` over an ignore; when SQLModel/SQLAlchemy typing forces it, use `# type: ignore[<code>]` with the exact error code on that line only; never add `ignore_errors`, never lower `strict`. Likely spots (fix only what mypy actually reports): `JobSource` Protocol members; `create_engine_from_url`'s `kwargs: dict` → `dict[str, Any]`; `UserPreferences.__table__`; `Job.__table_args__`; lambdas in `SOURCE_FACTORIES`; `typer`/`uvicorn` call signatures. Re-run until `Success: no issues found`.

- [ ] **Step 3: Verify nothing regressed**

Run: `uv run pytest -q` (96 passed, no warnings), `uv run ruff check .`, `uv run ruff format --check .`.

- [ ] **Step 4: Wire CI and docs**

`.github/workflows/ci.yml`: add `- run: uv run mypy src` after the `ruff format --check` step.
`README.md` Development block: add `uv run mypy src               # static typing (strict, src only)`.
`CLAUDE.md` Commands: add `- \`uv run mypy src\` — strict type check of \`src/\`; must be clean before committing (CI enforces it).` and update the **Current state** paragraph to: "Stages 0, 1 and 2a are implemented (see the plans in `docs/superpowers/plans/`). Next is stage 2b (LangGraph matching)."

- [ ] **Step 5: Commit**

```powershell
git add pyproject.toml uv.lock .github/workflows/ci.yml README.md CLAUDE.md src
git commit -m "chore: add mypy --strict for src to the dev workflow and CI" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Manual end-to-end check**

Run: `uv run jobscout fetch` then `uv run jobscout jobs --all --limit 3`.
Expected: `arbeitnow: fetched=500 created=... updated=... changed=...` (numbers vary; `updated` should now be large since the DB already has these jobs) and three real postings. No `User` row is created by `fetch`; `jobs` still bootstraps one.

---

## Self-review against the spec

- **§2 decisions → tasks:** ingest scope (T2), metadata refresh + ids (T3), engine seam (T1), filters (T4), `html_to_text` (T5), mypy (T7), non-nullable single source (T6). ✔
- **§3 parent-spec amendments:** already committed with the spec (`0a81260`); T7 updates `CLAUDE.md` current-state. ✔
- **§6 testing list:** every bullet has a test in T1–T6; CI mypy step in T7. ✔
- **§8 done-when:** T7 steps 3–6. ✔
- **Type consistency:** `run_ingest(session, settings, sources=None)` used identically in T2 tests and CLI; `UpsertStats.created_ids/changed_ids` names match in T3 tests, `ingest()` and `IngestResult`; `tokenize` public name used in T4 tests; `PROTECTED_PREFERENCE_FIELDS` / `non_nullable_preference_fields()` identical across T6 files; `get_engine(settings)` / `reset_engines()` identical in T1 code, conftest and CLI.
- **Test counts:** 79 → T1 +5 = 84 → T2 −1 +2 = 85 → T3 +3 = 88 → T4 +4 = 92 → T5 +2 = 94 → T6 +2 = 96.

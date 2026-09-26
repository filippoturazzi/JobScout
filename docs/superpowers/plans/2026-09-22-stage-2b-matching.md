# JobScout Stage 2b: LangGraph Matching — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score every worthwhile (job, user) pair 0–100 with a written justification, matched/missing skills and red flags, using cached embeddings and a cosine prefilter to keep LLM calls bounded and best-first.

**Architecture:** A new `matching/` package (no HTTP, no sources, no pipeline imports) holds the provider factory, vector helpers, prompt, structured-output schema and the LangGraph graph. `pipeline/matching.py` selects candidates (deterministic filter → batch embed → cosine → top-K under a cap) and runs the graph per selected job; `pipeline/backfill.py` and `pipeline/run.py::save_preferences` wire preference changes to it. API and CLI stay thin shells.

**Tech Stack:** Python 3.12, uv, LangGraph 1.2, langchain-core 1.6, langchain-google-genai 4.4 (Gemini default), SQLModel, FastAPI, Typer, pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-22-stage-2b-matching-design.md`

## Global Constraints

- Always `uv run ...` (Python 3.12 pinned); never the system Python. `uv` is at `$env:USERPROFILE\.local\bin\uv.exe` if not on PATH.
- **Unit tests never touch the network and never need an API key.** Embeddings use `langchain_core.embeddings.DeterministicFakeEmbedding`; the chat model uses the local double from Task 6. Real-API tests carry `@pytest.mark.integration` and are deselected by default.
- Dependency direction: `matching` imports only `config`, `models` and third-party — never `sources`, `pipeline`, `api`, `cli`. `pipeline` is the only composer. `api`/`cli` are thin.
- Operator config (env, `Settings`) never mixes with user preferences (DB). Provider keys are read from the environment by the provider packages; they are never stored in user tables.
- All datetimes naive UTC (`jobscout.models.base.utcnow()`).
- `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy src` clean before every commit. `mypy` is `--strict` with `warn_unused_ignores`: prefer annotations/`cast` over ignores; a `# type: ignore[code]` must carry the exact code and be needed.
- Test output pristine (no warnings). Existing tests keep passing unless a task says to change them.
- Every commit message ends with the trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` (second `-m`); conventional prefixes (`feat:`, `fix:`, `refactor:`, `test:`, `chore:`, `docs:`).
- Status values are exactly: `new`, `seen`, `saved`, `dismissed`, `notified`, `low`, `stale`. `low` is terminal until staled; `dismissed` is never re-evaluated and never marked stale.
- Defaults: `LLM_PROVIDER=google`, `LLM_MODEL=gemini-3.5-flash`, `EMBEDDING_MODEL=gemini-embedding-2`, `EMBEDDING_DIM=768`, `SIMILARITY_THRESHOLD=0.45`, `MAX_EMBEDDINGS_PER_RUN=200`, `MAX_LLM_EVALUATIONS_PER_RUN=25`. Confirmed against the real API in Task 13: `gemini-3.5-flash` exists as originally planned; the placeholder `gemini-embedding-001` does not exist (the API returns a misleading `429 RESOURCE_EXHAUSTED` for it rather than a 404) — the corrected default is `gemini-embedding-2`. `SIMILARITY_THRESHOLD` was raised from the original `0.35` after the live run showed a 0.503-0.695 observed similarity range over 30 active jobs, well above the old floor.
- Baseline: `main` @ `c17d118`, 96 unit tests passing, mypy clean.

---

## File Structure

```
src/jobscout/config.py                 + 6 settings                                   [Task 1]
pyproject.toml, .env.example           + langgraph, langchain-google-genai            [Task 1]
src/jobscout/matching/__init__.py      empty package marker                            [Task 2]
src/jobscout/matching/vectors.py       pack / unpack / cosine / dim                    [Task 2]
src/jobscout/matching/llm.py           chat_model / embeddings / MissingProviderError  [Task 3]
src/jobscout/models/match.py           Match table (+ re-export)                       [Task 4]
src/jobscout/matching/schemas.py       EvaluationResult, MatchState                    [Task 5]
src/jobscout/matching/prompts.py       SYSTEM_PROMPT, build_user_prompt, job_text,
                                       profile_text                                    [Task 5]
tests/matching/fakes.py                CountingChatModel double                        [Task 6]
src/jobscout/matching/graph.py         build_graph + 5 nodes                           [Task 6]
src/jobscout/pipeline/matching.py      MatchRun, select_candidates, run_match          [Task 7]
src/jobscout/pipeline/ingest.py        stale-marking for changed_ids                   [Task 8]
src/jobscout/pipeline/users.py         update_preferences -> changed fields; clears
                                       profile_embedding                               [Task 9]
src/jobscout/pipeline/backfill.py      backfill_matches                                [Task 10]
src/jobscout/pipeline/run.py           save_preferences                                [Task 10]
src/jobscout/api/deps.py               get_current_user_id                             [Task 11]
src/jobscout/api/schemas.py            MatchRead                                       [Task 11]
src/jobscout/api/routers/matches.py    GET /matches                                    [Task 11]
src/jobscout/api/routers/{jobs,preferences}.py, src/jobscout/cli.py  drop casts        [Task 11]
src/jobscout/cli.py                    match, matches commands                         [Task 12]
tests/integration/test_matching_live.py, README.md, CLAUDE.md, spec                    [Task 13]
```

---

### Task 1: Dependencies and settings

**Files:**
- Modify: `pyproject.toml`, `.env.example`, `src/jobscout/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.llm_provider`, `.llm_model`, `.embedding_model`, `.embedding_dim`, `.similarity_threshold`, `.max_llm_evaluations_per_run`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_config.py`)

```python
def test_matching_defaults():
    s = Settings(_env_file=None)
    assert s.llm_provider == "google"
    assert s.llm_model == "gemini-3.5-flash"
    assert s.embedding_model == "gemini-embedding-001"
    assert s.embedding_dim == 768
    assert s.similarity_threshold == 0.35
    assert s.max_llm_evaluations_per_run == 25


def test_matching_settings_from_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("SIMILARITY_THRESHOLD", "0.5")
    monkeypatch.setenv("MAX_LLM_EVALUATIONS_PER_RUN", "3")
    s = Settings(_env_file=None)
    assert s.llm_provider == "ollama"
    assert s.similarity_threshold == 0.5
    assert s.max_llm_evaluations_per_run == 3
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `'Settings' object has no attribute 'llm_provider'`.

- [ ] **Step 3: Add the settings**

In `src/jobscout/config.py`, after `api_port`:
```python
    llm_provider: str = "google"
    llm_model: str = "gemini-3.5-flash"
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768
    similarity_threshold: float = 0.35
    max_llm_evaluations_per_run: int = 25
```

- [ ] **Step 4: Add the dependencies**

In `pyproject.toml` `[project] dependencies` add:
```toml
    "langgraph>=1.2",
    "langchain-core>=1.6",
    "langchain-google-genai>=4.4",
```
Run: `uv sync --all-groups`

- [ ] **Step 5: Document them in `.env.example`**

Append:
```
# --- Matching (stage 2b). Only `jobscout match` and GET /matches need these. ---
# Provider for chat + embeddings: google | openai | ollama
LLM_PROVIDER=google
LLM_MODEL=gemini-3.5-flash
EMBEDDING_MODEL=gemini-embedding-001
# Requested embedding dimensionality; stored vectors of another size are re-embedded.
EMBEDDING_DIM=768
# Cosine floor below which a job never reaches the LLM.
SIMILARITY_THRESHOLD=0.35
# Hard cap on LLM evaluations per `match` run and per backfill.
MAX_LLM_EVALUATIONS_PER_RUN=25

# Provider key, read from the environment by the provider package:
GOOGLE_API_KEY=
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest -q` → 98 passed, no warnings. `uv run mypy src` → Success. `uv run ruff check . ; uv run ruff format .`

- [ ] **Step 7: Commit**

```powershell
git add pyproject.toml uv.lock .env.example src/jobscout/config.py tests/test_config.py
git commit -m "feat: add matching settings and LangGraph/Gemini dependencies" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Vector helpers

**Files:**
- Create: `src/jobscout/matching/__init__.py`, `src/jobscout/matching/vectors.py`, `tests/matching/__init__.py`, `tests/matching/test_vectors.py`

**Interfaces:**
- Produces: `pack(vector: Sequence[float]) -> bytes`; `unpack(blob: bytes) -> list[float]`; `dim(blob: bytes | None) -> int` (0 for `None`/empty); `cosine(a: Sequence[float], b: Sequence[float]) -> float` (0.0 when either norm is 0; raises `ValueError` on length mismatch).

- [ ] **Step 1: Write the failing tests**

`tests/matching/__init__.py`: empty. `src/jobscout/matching/__init__.py` is created in Step 3.

`tests/matching/test_vectors.py`:
```python
import math

import pytest

from jobscout.matching.vectors import cosine, dim, pack, unpack


def test_pack_unpack_roundtrip():
    vector = [0.5, -0.25, 0.125]
    restored = unpack(pack(vector))
    assert len(restored) == 3
    assert all(math.isclose(a, b, rel_tol=1e-6) for a, b in zip(vector, restored, strict=True))


def test_dim_counts_floats():
    assert dim(pack([1.0] * 768)) == 768
    assert dim(None) == 0
    assert dim(b"") == 0


def test_cosine_known_values():
    assert math.isclose(cosine([1.0, 0.0], [1.0, 0.0]), 1.0, rel_tol=1e-6)
    assert math.isclose(cosine([1.0, 0.0], [0.0, 1.0]), 0.0, abs_tol=1e-6)
    assert math.isclose(cosine([1.0, 0.0], [-1.0, 0.0]), -1.0, rel_tol=1e-6)
    assert math.isclose(cosine([3.0, 4.0], [3.0, 4.0]), 1.0, rel_tol=1e-6)


def test_cosine_zero_vector_is_zero():
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_length_mismatch_raises():
    with pytest.raises(ValueError, match="length"):
        cosine([1.0], [1.0, 2.0])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/matching/test_vectors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobscout.matching'`.

- [ ] **Step 3: Implement**

`src/jobscout/matching/__init__.py`:
```python
"""Embeddings, prompts and the LangGraph matching graph. Knows nothing about HTTP or the pipeline."""
```

`src/jobscout/matching/vectors.py`:
```python
"""Float vectors packed into the ``bytes`` columns, plus cosine similarity.

``array("f")`` keeps this dependency-free: 4 bytes per dimension, native float32.
At a few hundred jobs the pure-Python dot product costs milliseconds.
"""

import math
from array import array
from collections.abc import Sequence

_TYPECODE = "f"
_BYTES_PER_FLOAT = 4


def pack(vector: Sequence[float]) -> bytes:
    return array(_TYPECODE, vector).tobytes()


def unpack(blob: bytes) -> list[float]:
    values = array(_TYPECODE)
    values.frombytes(blob)
    return list(values)


def dim(blob: bytes | None) -> int:
    """Number of floats in a stored vector; 0 when absent."""
    if not blob:
        return 0
    return len(blob) // _BYTES_PER_FLOAT


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} != {len(b)}")
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/matching/test_vectors.py -v` → 5 passed. `uv run mypy src` → Success.

- [ ] **Step 5: Lint and commit**

```powershell
uv run ruff check . ; uv run ruff format .
git add src/jobscout/matching tests/matching
git commit -m "feat: add packed float vectors and cosine similarity" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Provider factory

**Files:**
- Create: `src/jobscout/matching/llm.py`, `tests/matching/test_llm.py`

**Interfaces:**
- Consumes: `Settings` (Task 1).
- Produces: `class MissingProviderError(RuntimeError)`; `chat_model(settings: Settings) -> BaseChatModel`; `embeddings(settings: Settings) -> Embeddings`; `PROVIDERS: dict[str, _ProviderBuilders]`.

- [ ] **Step 1: Write the failing tests**

`tests/matching/test_llm.py`:
```python
import pytest

from jobscout.config import Settings
from jobscout.matching.llm import MissingProviderError, chat_model, embeddings


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_unknown_provider_names_the_available_ones():
    with pytest.raises(MissingProviderError, match="nope"):
        chat_model(_settings(llm_provider="nope"))
    with pytest.raises(MissingProviderError, match="google"):
        embeddings(_settings(llm_provider="nope"))


def test_google_without_key_explains_what_to_set(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(MissingProviderError) as excinfo:
        chat_model(_settings(llm_provider="google"))
    assert "GOOGLE_API_KEY" in str(excinfo.value)


def test_missing_package_explains_the_install(monkeypatch):
    import jobscout.matching.llm as llm

    def _boom(name: str) -> None:
        raise ImportError(f"No module named {name!r}")

    monkeypatch.setattr(llm, "_import_module", _boom)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    with pytest.raises(MissingProviderError, match="pip install langchain-openai"):
        chat_model(_settings(llm_provider="openai"))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/matching/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobscout.matching.llm'`.

- [ ] **Step 3: Implement**

`src/jobscout/matching/llm.py`:
```python
"""Chat model and embeddings, chosen by ``LLM_PROVIDER``.

Providers are imported lazily so the project installs (and its tests run) with only the
default provider present. Keys are read from the environment by the provider packages.
"""

import importlib
import os
from dataclasses import dataclass
from types import ModuleType
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from jobscout.config import Settings


class MissingProviderError(RuntimeError):
    """The configured provider is unknown, not installed, or missing its API key."""


@dataclass(frozen=True)
class _Provider:
    module: str
    package: str
    chat_class: str
    embeddings_class: str
    key_env: str


PROVIDERS: dict[str, _Provider] = {
    "google": _Provider(
        module="langchain_google_genai",
        package="langchain-google-genai",
        chat_class="ChatGoogleGenerativeAI",
        embeddings_class="GoogleGenerativeAIEmbeddings",
        key_env="GOOGLE_API_KEY",
    ),
    "openai": _Provider(
        module="langchain_openai",
        package="langchain-openai",
        chat_class="ChatOpenAI",
        embeddings_class="OpenAIEmbeddings",
        key_env="OPENAI_API_KEY",
    ),
    "ollama": _Provider(
        module="langchain_ollama",
        package="langchain-ollama",
        chat_class="ChatOllama",
        embeddings_class="OllamaEmbeddings",
        key_env="",  # local server, no key
    ),
}


def _import_module(name: str) -> ModuleType:
    return importlib.import_module(name)


def _resolve(settings: Settings) -> tuple[_Provider, ModuleType]:
    provider = PROVIDERS.get(settings.llm_provider)
    if provider is None:
        available = ", ".join(sorted(PROVIDERS))
        raise MissingProviderError(
            f"Unknown LLM_PROVIDER {settings.llm_provider!r}. Available: {available}."
        )
    if provider.key_env and not os.environ.get(provider.key_env):
        raise MissingProviderError(
            f"{provider.key_env} is not set. Matching needs it for provider "
            f"{settings.llm_provider!r} — see .env.example."
        )
    try:
        module = _import_module(provider.module)
    except ImportError as exc:
        raise MissingProviderError(
            f"Provider {settings.llm_provider!r} needs the {provider.package} package: "
            f"pip install {provider.package}"
        ) from exc
    return provider, module


def chat_model(settings: Settings) -> BaseChatModel:
    provider, module = _resolve(settings)
    factory: Any = getattr(module, provider.chat_class)
    return factory(model=settings.llm_model, temperature=0)  # type: ignore[no-any-return]


def embeddings(settings: Settings) -> Embeddings:
    provider, module = _resolve(settings)
    factory: Any = getattr(module, provider.embeddings_class)
    return factory(model=settings.embedding_model)  # type: ignore[no-any-return]
```

Note on the two ignores: the provider classes are reached via `getattr`, so mypy sees `Any`. If `--strict` does not actually complain (because `Any` is returned where a protocol is expected), delete the ignore — `warn_unused_ignores` will tell you.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/matching/test_llm.py -v` → 4 passed. `uv run mypy src` → Success.

- [ ] **Step 5: Lint and commit**

```powershell
uv run ruff check . ; uv run ruff format .
git add src/jobscout/matching/llm.py tests/matching/test_llm.py
git commit -m "feat: add the LLM provider factory with lazy imports" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `Match` model

**Files:**
- Create: `src/jobscout/models/match.py`, `tests/test_match_model.py`
- Modify: `src/jobscout/models/__init__.py`

**Interfaces:**
- Produces: `Match` table with the fields in spec §4, plus `MATCH_STATUSES: frozenset[str]` and `REEVALUATABLE_STATUSES: frozenset[str]` (`{"stale"}`), re-exported from `jobscout.models`.

- [ ] **Step 1: Write the failing tests**

`tests/test_match_model.py`:
```python
import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from jobscout.models import Job, Match, User


def _job(session, external_id="j1") -> Job:
    job = Job(
        source="t",
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        url=f"https://x/{external_id}",
        description="d",
        content_hash="h",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _user(session) -> User:
    user = User(email="a@b")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_match_roundtrip_defaults(session):
    job, user = _job(session), _user(session)
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.42))
    session.commit()
    match = session.exec(select(Match)).one()
    assert match.score is None and match.reasoning is None
    assert match.matched_skills == [] and match.missing_skills == [] and match.red_flags == []
    assert match.status == "new"
    assert match.llm_model is None
    assert match.created_at.tzinfo is None


def test_match_is_unique_per_job_and_user(session):
    job, user = _job(session), _user(session)
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.1))
    session.commit()
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.2))
    with pytest.raises(IntegrityError):
        session.commit()


def test_status_sets_are_consistent():
    from jobscout.models.match import MATCH_STATUSES, REEVALUATABLE_STATUSES

    assert MATCH_STATUSES == frozenset(
        {"new", "seen", "saved", "dismissed", "notified", "low", "stale"}
    )
    assert REEVALUATABLE_STATUSES == frozenset({"stale"})
    assert "dismissed" not in REEVALUATABLE_STATUSES
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_match_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'Match' from 'jobscout.models'`.

- [ ] **Step 3: Implement**

`src/jobscout/models/match.py`:
```python
from datetime import datetime

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from jobscout.models.base import utcnow

MATCH_STATUSES: frozenset[str] = frozenset(
    {"new", "seen", "saved", "dismissed", "notified", "low", "stale"}
)
"""`low` = rejected by the cosine prefilter (terminal until staled); `stale` = needs re-evaluation."""

REEVALUATABLE_STATUSES: frozenset[str] = frozenset({"stale"})
"""Statuses a new run may pick up again. `dismissed` is deliberately absent."""


class Match(SQLModel, table=True):
    """One evaluated (job, user) pair."""

    __table_args__ = (UniqueConstraint("job_id", "user_id", name="uq_match_job_user"),)

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="job.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    similarity: float
    score: int | None = None
    reasoning: str | None = None
    matched_skills: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    missing_skills: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    red_flags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    status: str = Field(default="new", index=True)
    llm_model: str | None = None
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(
        default_factory=utcnow, nullable=False, sa_column_kwargs={"onupdate": utcnow}
    )
```

`src/jobscout/models/__init__.py` — add to the imports and `__all__`:
```python
from jobscout.models.match import MATCH_STATUSES, REEVALUATABLE_STATUSES, Match
```
(`__all__` entries: `"MATCH_STATUSES"`, `"Match"`, `"REEVALUATABLE_STATUSES"`; keep ruff's sorting.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_match_model.py -v` → 3 passed. `uv run mypy src` → Success.

- [ ] **Step 5: Lint and commit**

```powershell
uv run ruff check . ; uv run ruff format .
git add src/jobscout/models tests/test_match_model.py
git commit -m "feat: add the Match table" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Evaluation schema, state and prompts

**Files:**
- Create: `src/jobscout/matching/schemas.py`, `src/jobscout/matching/prompts.py`, `tests/matching/test_prompts.py`

**Interfaces:**
- Consumes: `Job`, `UserPreferences` (models).
- Produces:
  - `EvaluationResult(BaseModel)`: `score: int` (0–100), `reasoning: str`, `matched_skills: list[str]`, `missing_skills: list[str]`, `red_flags: list[str]`.
  - `MatchState(TypedDict, total=False)`: `job_id, user_id, job_text, prompt, profile_text, job_embedding, profile_embedding, similarity, evaluation, llm_model, should_notify`. `prompt` is the fully built user message (Task 7 fills it); `job_text` is the raw rendering used for embedding.
  - `SYSTEM_PROMPT: str`; `profile_text(prefs: UserPreferences) -> str`; `job_text(job: Job) -> str`; `build_user_prompt(prefs: UserPreferences, job: Job, locale: str) -> str`; `MAX_DESCRIPTION_CHARS = 6000`.

- [ ] **Step 1: Write the failing tests**

`tests/matching/test_prompts.py`:
```python
from jobscout.matching.prompts import (
    MAX_DESCRIPTION_CHARS,
    SYSTEM_PROMPT,
    build_user_prompt,
    job_text,
    profile_text,
)
from jobscout.models import Job, UserPreferences


def _prefs() -> UserPreferences:
    return UserPreferences(
        user_id=1,
        titles=["AI Engineer"],
        seniority=["junior"],
        required_skills=["Python"],
        nice_to_have_skills=["LangGraph"],
        regions=["Germany"],
        work_modes=["remote"],
        min_salary=60000,
        profile_summary="Junior AI engineer, Python, building LLM apps.",
    )


def _job(description="Build LLM pipelines in Python.") -> Job:
    return Job(
        source="arbeitnow",
        external_id="x",
        title="AI Engineer",
        company="Acme",
        location="Berlin, Germany",
        remote=True,
        url="https://x/1",
        description=description,
        tags=["python", "llm"],
        content_hash="h",
    )


def test_profile_text_includes_summary_and_preferences():
    text = profile_text(_prefs())
    assert "Junior AI engineer" in text
    assert "AI Engineer" in text and "Python" in text and "LangGraph" in text
    assert "Germany" in text and "remote" in text


def test_job_text_includes_metadata_and_truncates_description():
    text = job_text(_job(description="x" * (MAX_DESCRIPTION_CHARS + 500)))
    assert "AI Engineer" in text and "Acme" in text and "Berlin" in text and "python" in text
    assert len(text) < MAX_DESCRIPTION_CHARS + 600
    assert text.endswith("…")


def test_user_prompt_carries_both_sides_and_the_locale():
    prompt = build_user_prompt(_prefs(), _job(), locale="pt")
    assert "Junior AI engineer" in prompt
    assert "Build LLM pipelines" in prompt
    assert "pt" in prompt


def test_system_prompt_demands_evidence_and_conservatism():
    lowered = SYSTEM_PROMPT.lower()
    assert "only" in lowered and "score" in lowered
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/matching/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobscout.matching.prompts'`.

- [ ] **Step 3: Implement `schemas.py`**

```python
"""The LLM's structured output and the graph's state."""

from typing import TypedDict

from pydantic import BaseModel, Field


class EvaluationResult(BaseModel):
    """What the LLM must return for one (job, profile) pair."""

    score: int = Field(ge=0, le=100, description="Fit from 0 (irrelevant) to 100 (ideal).")
    reasoning: str = Field(description="Two or three sentences justifying the score.")
    matched_skills: list[str] = Field(
        default_factory=list, description="Skills required by the job that the profile has."
    )
    missing_skills: list[str] = Field(
        default_factory=list, description="Skills required by the job that the profile lacks."
    )
    red_flags: list[str] = Field(
        default_factory=list,
        description="Concrete mismatches: seniority, location, salary, contract type.",
    )


class MatchState(TypedDict, total=False):
    """State threaded through the matching graph, one run per (job, user)."""

    job_id: int
    user_id: int
    job_text: str
    prompt: str
    profile_text: str
    job_embedding: list[float]
    profile_embedding: list[float]
    similarity: float
    evaluation: EvaluationResult | None
    llm_model: str | None
    should_notify: bool
```

- [ ] **Step 4: Implement `prompts.py`**

```python
"""Prompt construction. Pure functions over models — no I/O."""

from jobscout.models import Job, UserPreferences

MAX_DESCRIPTION_CHARS = 6000

SYSTEM_PROMPT = """You evaluate how well a job posting fits a candidate's profile.

Rules:
- Be conservative: a high score means the candidate could apply today with a real chance.
- Use only what the two texts state. Never invent skills, seniority or benefits.
- List a skill under matched_skills only if the job asks for it AND the profile shows it.
- red_flags are concrete mismatches (seniority far off, wrong location for an on-site role,
  salary below the stated minimum, contract type), not vague doubts.
- Score bands: 0-39 wrong role, 40-59 adjacent, 60-79 plausible, 80-100 strong fit."""


def profile_text(prefs: UserPreferences) -> str:
    """One paragraph describing the candidate — also the text that gets embedded."""
    parts = [prefs.profile_summary.strip()]
    for label, values in (
        ("Target titles", prefs.titles),
        ("Seniority", prefs.seniority),
        ("Required skills", prefs.required_skills),
        ("Nice to have", prefs.nice_to_have_skills),
        ("Regions", prefs.regions),
        ("Work modes", prefs.work_modes),
    ):
        if values:
            parts.append(f"{label}: {', '.join(values)}.")
    if prefs.min_salary:
        currency = prefs.salary_currency or ""
        parts.append(f"Minimum salary: {prefs.min_salary} {currency}".strip() + ".")
    return " ".join(part for part in parts if part)


def job_text(job: Job) -> str:
    """Job rendered for embedding and for the prompt; description truncated."""
    description = job.description.strip()
    if len(description) > MAX_DESCRIPTION_CHARS:
        description = description[:MAX_DESCRIPTION_CHARS].rstrip() + "…"
    header = [
        f"Title: {job.title}",
        f"Company: {job.company}",
        f"Location: {'remote' if job.remote else (job.location or 'not stated')}",
    ]
    if job.salary_min or job.salary_max:
        header.append(
            f"Salary: {job.salary_min or '?'}-{job.salary_max or '?'} {job.salary_currency or ''}".strip()
        )
    if job.tags:
        header.append(f"Tags: {', '.join(job.tags)}")
    return "\n".join(header) + f"\n\n{description}"


def build_user_prompt(prefs: UserPreferences, job: Job, locale: str) -> str:
    return (
        f"CANDIDATE PROFILE:\n{profile_text(prefs)}\n\n"
        f"JOB POSTING:\n{job_text(job)}\n\n"
        f"Write `reasoning` in the language with code '{locale}'. "
        "Everything else stays in English."
    )
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/matching/test_prompts.py -v` → 4 passed. `uv run mypy src` → Success.

- [ ] **Step 6: Lint and commit**

```powershell
uv run ruff check . ; uv run ruff format .
git add src/jobscout/matching/schemas.py src/jobscout/matching/prompts.py tests/matching/test_prompts.py
git commit -m "feat: add the evaluation schema, graph state and prompts" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: The matching graph

**Files:**
- Create: `src/jobscout/matching/graph.py`, `tests/matching/fakes.py`, `tests/matching/test_graph.py`

**Interfaces:**
- Consumes: `MatchState`, `EvaluationResult` (Task 5); `cosine` (Task 2).
- Produces:
  - `@dataclass GraphDeps`: `chat: BaseChatModel`, `embed: Embeddings`, `threshold: float`, `model_name: str`.
  - `build_graph(deps: GraphDeps) -> CompiledStateGraph[MatchState]`.
  - Test double `CountingChatModel` in `tests/matching/fakes.py` with `.calls: int` and `.with_structured_output(schema)` returning an object whose `.invoke(messages)` yields the next canned `EvaluationResult`.

- [ ] **Step 1: Write the double and the failing tests**

`tests/matching/fakes.py`:
```python
"""Test doubles. The langchain fake chat models do not implement structured output usefully."""

from typing import Any

from jobscout.matching.schemas import EvaluationResult


class _StructuredRunnable:
    def __init__(self, parent: "CountingChatModel") -> None:
        self._parent = parent

    def invoke(self, _messages: Any) -> EvaluationResult:
        self._parent.calls += 1
        if self._parent.error is not None:
            raise self._parent.error
        index = min(self._parent.calls - 1, len(self._parent.results) - 1)
        return self._parent.results[index]


class CountingChatModel:
    """Counts `.invoke` calls so a test can prove the LLM was skipped."""

    def __init__(
        self, results: list[EvaluationResult] | None = None, error: Exception | None = None
    ) -> None:
        self.results = results or [
            EvaluationResult(
                score=75,
                reasoning="Good overlap on Python and LLM work.",
                matched_skills=["Python"],
                missing_skills=["Kubernetes"],
                red_flags=[],
            )
        ]
        self.error = error
        self.calls = 0

    def with_structured_output(self, _schema: Any) -> _StructuredRunnable:
        return _StructuredRunnable(self)
```

`tests/matching/test_graph.py`:
```python
from langchain_core.embeddings import DeterministicFakeEmbedding

from jobscout.matching.graph import GraphDeps, build_graph
from jobscout.matching.schemas import EvaluationResult
from tests.matching.fakes import CountingChatModel

DIM = 8


def _deps(chat: CountingChatModel, threshold: float) -> GraphDeps:
    return GraphDeps(
        chat=chat,  # type: ignore[arg-type]
        embed=DeterministicFakeEmbedding(size=DIM),
        threshold=threshold,
        model_name="fake-model",
    )


def _state(**kw):
    base = {
        "job_id": 1,
        "user_id": 1,
        "job_text": "Python LLM engineer in Berlin",
        "profile_text": "Python LLM engineer",
        "profile_embedding": DeterministicFakeEmbedding(size=DIM).embed_query("Python LLM engineer"),
    }
    base.update(kw)
    return base


def test_low_similarity_skips_the_llm():
    chat = CountingChatModel()
    graph = build_graph(_deps(chat, threshold=1.1))  # nothing can clear this

    final = graph.invoke(_state())

    assert chat.calls == 0
    assert final["evaluation"] is None
    assert final["should_notify"] is False
    assert "similarity" in final


def test_high_similarity_evaluates_and_decides():
    chat = CountingChatModel(
        results=[
            EvaluationResult(score=90, reasoning="Strong fit.", matched_skills=["Python"]),
        ]
    )
    graph = build_graph(_deps(chat, threshold=-1.0))  # everything clears this

    final = graph.invoke(_state())

    assert chat.calls == 1
    evaluation = final["evaluation"]
    assert evaluation is not None and evaluation.score == 90
    assert final["llm_model"] == "fake-model"


def test_embed_job_uses_the_cached_vector():
    chat = CountingChatModel()
    graph = build_graph(_deps(chat, threshold=-1.0))
    cached = [1.0] * DIM

    final = graph.invoke(_state(job_embedding=cached))

    assert final["job_embedding"] == cached


def test_identical_texts_score_similarity_one():
    chat = CountingChatModel()
    graph = build_graph(_deps(chat, threshold=-1.0))
    text = "Python LLM engineer"
    profile = DeterministicFakeEmbedding(size=DIM).embed_query(text)

    final = graph.invoke(_state(job_text=text, profile_text=text, profile_embedding=profile))

    assert final["similarity"] > 0.999
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/matching/test_graph.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobscout.matching.graph'`.

- [ ] **Step 3: Implement**

`src/jobscout/matching/graph.py`:
```python
"""The per-(job, user) matching graph.

    embed_job ─► prefilter ─(below threshold)─► record_low ─► END
                       └────(at or above)─────► evaluate ─► decide ─► END

The conditional edge is the cost control: a job that does not clear the cosine floor never
reaches the LLM. Persistence happens in ``pipeline.matching``; this module stays I/O-free
apart from the model calls it is handed.
"""

from dataclasses import dataclass
from typing import Literal

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from jobscout.matching.prompts import SYSTEM_PROMPT
from jobscout.matching.schemas import EvaluationResult, MatchState
from jobscout.matching.vectors import cosine


@dataclass
class GraphDeps:
    """Everything the nodes need, injected so tests can pass doubles."""

    chat: BaseChatModel
    embed: Embeddings
    threshold: float
    model_name: str


def build_graph(deps: GraphDeps) -> object:
    """Compile the matching graph. Returns a LangGraph ``CompiledStateGraph``."""

    def embed_job(state: MatchState) -> MatchState:
        if state.get("job_embedding"):
            return {}
        vector = deps.embed.embed_query(state["job_text"])
        return {"job_embedding": vector}

    def prefilter(state: MatchState) -> MatchState:
        similarity = cosine(state["job_embedding"], state["profile_embedding"])
        return {"similarity": similarity}

    def route(state: MatchState) -> Literal["record_low", "evaluate"]:
        return "evaluate" if state["similarity"] >= deps.threshold else "record_low"

    def record_low(_state: MatchState) -> MatchState:
        return {"evaluation": None, "llm_model": None, "should_notify": False}

    def evaluate(state: MatchState) -> MatchState:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            # `prompt` carries profile + job (pipeline.matching builds it); `job_text`
            # alone is the standalone fallback that keeps the graph runnable on its own.
            HumanMessage(content=state.get("prompt") or state["job_text"]),
        ]
        structured = deps.chat.with_structured_output(EvaluationResult)
        evaluation = structured.invoke(messages)
        return {"evaluation": evaluation, "llm_model": deps.model_name}

    def decide(state: MatchState) -> MatchState:
        evaluation = state.get("evaluation")
        return {"should_notify": evaluation is not None}

    builder: StateGraph = StateGraph(MatchState)
    builder.add_node("embed_job", embed_job)
    builder.add_node("prefilter", prefilter)
    builder.add_node("record_low", record_low)
    builder.add_node("evaluate", evaluate)
    builder.add_node("decide", decide)

    builder.add_edge(START, "embed_job")
    builder.add_edge("embed_job", "prefilter")
    builder.add_conditional_edges("prefilter", route)
    builder.add_edge("record_low", END)
    builder.add_edge("evaluate", "decide")
    builder.add_edge("decide", END)

    return builder.compile()
```

One implementation note: `should_notify` here only reports whether an evaluation happened; Task 7 is where a score is compared against the user's `min_score_to_notify` (stage 4 consumes that).

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/matching -v` → all pass. `uv run mypy src` → Success. If mypy objects to `build_graph`'s return type, annotate it as `CompiledStateGraph[MatchState, None, MatchState, MatchState]` only if that exact generic arity type-checks against the installed LangGraph; otherwise keep `object` and note it in the report.

- [ ] **Step 5: Lint and commit**

```powershell
uv run ruff check . ; uv run ruff format .
git add src/jobscout/matching/graph.py src/jobscout/matching/schemas.py tests/matching/fakes.py tests/matching/test_graph.py
git commit -m "feat: add the LangGraph matching graph with a cost-gating prefilter" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Candidate selection and `run_match`

**Files:**
- Create: `src/jobscout/pipeline/matching.py`, `tests/pipeline/test_matching.py`

**Interfaces:**
- Consumes: `build_graph`, `GraphDeps` (Task 6); `chat_model`, `embeddings`, `MissingProviderError` (Task 3); `pack`, `unpack`, `dim`, `cosine` (Task 2); `profile_text`, `job_text`, `build_user_prompt` (Task 5); `Match`, `REEVALUATABLE_STATUSES` (Task 4); `job_matches_preferences` (existing); `get_preferences` (existing).
- Produces:
  - `@dataclass MatchRun`: `evaluated: int = 0`, `skipped_low: int = 0`, `candidates: int = 0`, `errors: list[str] = []`, `error: str | None = None`, `previewed: list[tuple[int, float, str]] = []` (job id, similarity, title — dry run only).
  - `select_candidates(session, prefs, user_id) -> list[Job]`
  - `run_match(session, settings, user_id, limit=None, dry_run=False, deps=None) -> MatchRun`

- [ ] **Step 1: Write the failing tests**

`tests/pipeline/test_matching.py`:
```python
import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from sqlmodel import select

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps
from jobscout.matching.schemas import EvaluationResult
from jobscout.models import Job, Match
from jobscout.pipeline.matching import run_match, select_candidates
from jobscout.pipeline.users import get_or_create_default_user, update_preferences
from tests.matching.fakes import CountingChatModel

DIM = 8


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _deps(chat: CountingChatModel, threshold: float = -1.0) -> GraphDeps:
    return GraphDeps(
        chat=chat,  # type: ignore[arg-type]
        embed=DeterministicFakeEmbedding(size=DIM),
        threshold=threshold,
        model_name="fake-model",
    )


def _add_job(session, external_id: str, title: str = "AI Engineer") -> Job:
    job = Job(
        source="t",
        external_id=external_id,
        title=title,
        company="Acme",
        location="Berlin, Germany",
        remote=True,
        url=f"https://x/{external_id}",
        description=f"{title} building Python LLM systems.",
        content_hash=f"h-{external_id}",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _user_with_profile(session):
    user = get_or_create_default_user(session)
    update_preferences(
        session,
        user.id,
        {"titles": ["AI Engineer"], "profile_summary": "Python LLM engineer."},
    )
    return user


def test_no_profile_summary_evaluates_nothing(session):
    user = get_or_create_default_user(session)
    _add_job(session, "a")
    result = run_match(session, _settings(), user.id, deps=_deps(CountingChatModel()))
    assert result.evaluated == 0
    assert result.error is not None and "profile" in result.error.lower()


def test_evaluates_candidates_and_persists_matches(session):
    user = _user_with_profile(session)
    job = _add_job(session, "a")
    chat = CountingChatModel(
        results=[EvaluationResult(score=88, reasoning="Fits.", matched_skills=["Python"])]
    )

    result = run_match(session, _settings(), user.id, deps=_deps(chat))

    assert (result.evaluated, chat.calls) == (1, 1)
    match = session.exec(select(Match)).one()
    assert match.job_id == job.id and match.user_id == user.id
    assert match.score == 88 and match.status == "new"
    assert match.matched_skills == ["Python"] and match.llm_model == "fake-model"
    assert 0.0 <= match.similarity <= 1.0
    session.refresh(job)
    assert job.embedding is not None, "the job embedding must be cached"


def test_below_threshold_writes_low_without_calling_the_llm(session):
    user = _user_with_profile(session)
    _add_job(session, "a")
    chat = CountingChatModel()

    result = run_match(session, _settings(), user.id, deps=_deps(chat, threshold=1.1))

    assert chat.calls == 0
    assert (result.evaluated, result.skipped_low) == (0, 1)
    match = session.exec(select(Match)).one()
    assert match.status == "low" and match.score is None


def test_second_run_is_idempotent(session):
    user = _user_with_profile(session)
    _add_job(session, "a")
    chat = CountingChatModel()
    run_match(session, _settings(), user.id, deps=_deps(chat))

    second = run_match(session, _settings(), user.id, deps=_deps(chat))

    assert second.evaluated == 0 and chat.calls == 1
    assert len(session.exec(select(Match)).all()) == 1


def test_cap_limits_evaluations_and_takes_the_best_first(session):
    user = _user_with_profile(session)
    for i in range(5):
        _add_job(session, f"j{i}")
    chat = CountingChatModel()

    result = run_match(
        session, _settings(max_llm_evaluations_per_run=2), user.id, deps=_deps(chat)
    )

    assert (result.evaluated, chat.calls) == (2, 2)
    evaluated = session.exec(select(Match)).all()
    assert len(evaluated) == 2
    remaining = [
        job
        for job in session.exec(select(Job)).all()
        if job.id not in {m.job_id for m in evaluated}
    ]
    assert len(remaining) == 3, "unselected candidates keep no row"


def test_stale_is_reevaluated_and_dismissed_is_not(session):
    user = _user_with_profile(session)
    stale_job = _add_job(session, "stale-one")
    dismissed_job = _add_job(session, "dismissed-one")
    session.add(Match(job_id=stale_job.id, user_id=user.id, similarity=0.9, status="stale"))
    session.add(
        Match(job_id=dismissed_job.id, user_id=user.id, similarity=0.9, status="dismissed")
    )
    session.commit()
    chat = CountingChatModel()

    result = run_match(session, _settings(), user.id, deps=_deps(chat))

    assert result.evaluated == 1
    refreshed = {m.job_id: m for m in session.exec(select(Match)).all()}
    assert refreshed[stale_job.id].status == "new"
    assert refreshed[dismissed_job.id].status == "dismissed"


def test_dry_run_previews_without_calling_the_llm(session):
    user = _user_with_profile(session)
    _add_job(session, "a")
    chat = CountingChatModel()

    result = run_match(session, _settings(), user.id, dry_run=True, deps=_deps(chat))

    assert chat.calls == 0 and result.evaluated == 0
    assert len(result.previewed) == 1
    assert session.exec(select(Match)).all() == []


def test_llm_failure_is_isolated(session):
    user = _user_with_profile(session)
    _add_job(session, "a")
    _add_job(session, "b")
    chat = CountingChatModel(error=RuntimeError("rate limited"))

    result = run_match(session, _settings(), user.id, deps=_deps(chat))

    assert result.evaluated == 0
    assert len(result.errors) == 2 and "rate limited" in result.errors[0]
    assert session.exec(select(Match)).all() == []


def test_select_candidates_applies_the_deterministic_filter(session):
    from jobscout.pipeline.users import get_preferences

    user = _user_with_profile(session)
    _add_job(session, "good", title="AI Engineer")
    _add_job(session, "bad", title="Data Analyst")

    candidates = select_candidates(session, get_preferences(session, user.id), user.id)

    assert [job.external_id for job in candidates] == ["good"]


def test_missing_provider_surfaces_as_error(session, monkeypatch):
    user = _user_with_profile(session)
    _add_job(session, "a")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(Exception, match="GOOGLE_API_KEY"):
        run_match(session, _settings(), user.id)  # no deps -> real factory
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pipeline/test_matching.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobscout.pipeline.matching'`.

- [ ] **Step 3: Implement**

`src/jobscout/pipeline/matching.py`:
```python
"""Select what deserves an LLM call, run the graph on it, persist the result.

Selection lives here (not in the graph) so the batch embedding call and the top-K ranking
happen once per run instead of once per job.
"""

import logging
from dataclasses import dataclass, field

from sqlmodel import Session, col, select

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps, build_graph
from jobscout.matching.llm import chat_model, embeddings
from jobscout.matching.prompts import build_user_prompt, job_text, profile_text
from jobscout.matching.vectors import cosine, dim, pack, unpack
from jobscout.models import Job, Match, User, UserPreferences
from jobscout.pipeline.filters import job_matches_preferences
from jobscout.pipeline.users import get_preferences

log = logging.getLogger(__name__)

_EMBED_CHUNK = 100


@dataclass
class MatchRun:
    candidates: int = 0
    evaluated: int = 0
    skipped_low: int = 0
    errors: list[str] = field(default_factory=list)
    error: str | None = None
    previewed: list[tuple[int, float, str]] = field(default_factory=list)


def select_candidates(session: Session, prefs: UserPreferences, user_id: int) -> list[Job]:
    """Active jobs passing the deterministic filter that have no match, or a stale one."""
    existing: dict[int, str] = {
        match.job_id: match.status
        for match in session.exec(select(Match).where(Match.user_id == user_id)).all()
    }
    jobs = session.exec(select(Job).where(col(Job.is_active).is_(True))).all()
    return [
        job
        for job in jobs
        if job.id is not None
        and existing.get(job.id, "stale") == "stale"
        and job_matches_preferences(job, prefs)
    ]


def _ensure_profile_embedding(
    session: Session, prefs: UserPreferences, deps: GraphDeps, wanted_dim: int
) -> list[float]:
    if prefs.profile_embedding is not None and dim(prefs.profile_embedding) == wanted_dim:
        return unpack(prefs.profile_embedding)
    vector = deps.embed.embed_query(profile_text(prefs))
    prefs.profile_embedding = pack(vector)
    session.add(prefs)
    session.commit()
    return vector


def _ensure_job_embeddings(
    session: Session, jobs: list[Job], deps: GraphDeps, wanted_dim: int
) -> dict[int, list[float]]:
    vectors: dict[int, list[float]] = {}
    missing: list[Job] = []
    for job in jobs:
        if job.id is None:
            continue
        if job.embedding is not None and dim(job.embedding) == wanted_dim:
            vectors[job.id] = unpack(job.embedding)
        else:
            missing.append(job)

    for start in range(0, len(missing), _EMBED_CHUNK):
        chunk = missing[start : start + _EMBED_CHUNK]
        computed = deps.embed.embed_documents([job_text(job) for job in chunk])
        for job, vector in zip(chunk, computed, strict=True):
            assert job.id is not None
            job.embedding = pack(vector)
            vectors[job.id] = vector
            session.add(job)
    if missing:
        session.commit()
    return vectors


def _upsert_match(session: Session, job_id: int, user_id: int, **values: object) -> None:
    match = session.exec(
        select(Match).where(Match.job_id == job_id, Match.user_id == user_id)
    ).first()
    if match is None:
        match = Match(job_id=job_id, user_id=user_id, similarity=0.0)
    for name, value in values.items():
        setattr(match, name, value)
    session.add(match)


def _default_deps(settings: Settings) -> GraphDeps:
    return GraphDeps(
        chat=chat_model(settings),
        embed=embeddings(settings),
        threshold=settings.similarity_threshold,
        model_name=settings.llm_model,
    )


def run_match(
    session: Session,
    settings: Settings,
    user_id: int,
    limit: int | None = None,
    dry_run: bool = False,
    deps: GraphDeps | None = None,
) -> MatchRun:
    """Evaluate the best unmatched candidates for one user, bounded by the per-run cap."""
    result = MatchRun()
    prefs = get_preferences(session, user_id)
    if not prefs.profile_summary.strip():
        result.error = "No profile summary set — nothing to match against."
        return result

    candidates = select_candidates(session, prefs, user_id)
    result.candidates = len(candidates)
    if not candidates:
        return result

    deps = deps or _default_deps(settings)
    wanted_dim = settings.embedding_dim
    profile_vector = _ensure_profile_embedding(session, prefs, deps, wanted_dim)
    # The profile embedding fixes the dimension the job vectors must match.
    wanted_dim = len(profile_vector)
    job_vectors = _ensure_job_embeddings(session, candidates, deps, wanted_dim)

    ranked = sorted(
        (
            (cosine(job_vectors[job.id], profile_vector), job)
            for job in candidates
            if job.id is not None and job.id in job_vectors
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    cap = limit if limit is not None else settings.max_llm_evaluations_per_run
    selected = ranked[:cap]

    if dry_run:
        result.previewed = [
            (job.id, similarity, job.title) for similarity, job in selected if job.id is not None
        ]
        return result

    user = session.get(User, user_id)
    locale = user.locale if user is not None else "en"
    graph = build_graph(deps)

    for similarity, job in selected:
        assert job.id is not None
        state = {
            "job_id": job.id,
            "user_id": user_id,
            "job_text": job_text(job),
            "prompt": build_user_prompt(prefs, job, locale),
            "profile_text": profile_text(prefs),
            "job_embedding": job_vectors[job.id],
            "profile_embedding": profile_vector,
        }
        try:
            final = graph.invoke(state)  # type: ignore[attr-defined]
        except Exception as exc:  # isolate one bad evaluation from the rest of the run
            log.error("matching failed for job %s: %s: %s", job.id, type(exc).__name__, exc)
            result.errors.append(f"job {job.id}: {type(exc).__name__}: {exc}")
            continue

        evaluation = final.get("evaluation")
        if evaluation is None:
            _upsert_match(
                session,
                job.id,
                user_id,
                similarity=final["similarity"],
                score=None,
                reasoning=None,
                matched_skills=[],
                missing_skills=[],
                red_flags=[],
                status="low",
                llm_model=None,
            )
            result.skipped_low += 1
        else:
            _upsert_match(
                session,
                job.id,
                user_id,
                similarity=final["similarity"],
                score=evaluation.score,
                reasoning=evaluation.reasoning,
                matched_skills=evaluation.matched_skills,
                missing_skills=evaluation.missing_skills,
                red_flags=evaluation.red_flags,
                status="new",
                llm_model=final.get("llm_model"),
            )
            result.evaluated += 1
        session.commit()

    return result
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/pipeline/test_matching.py -v` → 10 passed. Then `uv run pytest -q` and `uv run mypy src`.

- [ ] **Step 5: Lint and commit**

```powershell
uv run ruff check . ; uv run ruff format .
git add src/jobscout/pipeline/matching.py tests/pipeline/test_matching.py
git commit -m "feat: add candidate selection and bounded match runs" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Stale-marking on ingest

**Files:**
- Modify: `src/jobscout/pipeline/ingest.py`
- Modify: `tests/pipeline/test_ingest.py`

**Interfaces:**
- Consumes: `Match` (Task 4), `stats.changed_ids` (existing).
- Produces: after a content change, that job's non-`dismissed` matches have `status == "stale"`.

- [ ] **Step 1: Write the failing test** (append to `tests/pipeline/test_ingest.py`)

```python
def test_changed_jobs_mark_matches_stale_except_dismissed(session):
    from jobscout.models import Match, User

    upsert_jobs(session, [raw("j1"), raw("j2")], now=T0)
    jobs = {j.external_id: j for j in session.exec(select(Job)).all()}
    user_a = User(email="a@b")
    user_b = User(email="b@b")
    session.add(user_a)
    session.add(user_b)
    session.commit()
    session.add(Match(job_id=jobs["j1"].id, user_id=user_a.id, similarity=0.9, status="new"))
    session.add(Match(job_id=jobs["j1"].id, user_id=user_b.id, similarity=0.9, status="dismissed"))
    session.add(Match(job_id=jobs["j2"].id, user_id=user_a.id, similarity=0.9, status="new"))
    session.commit()

    upsert_jobs(session, [raw("j1", description="brand new text"), raw("j2")], now=T0)

    statuses = {
        (m.job_id, m.user_id): m.status for m in session.exec(select(Match)).all()
    }
    assert statuses[(jobs["j1"].id, user_a.id)] == "stale"
    assert statuses[(jobs["j1"].id, user_b.id)] == "dismissed"
    assert statuses[(jobs["j2"].id, user_a.id)] == "new", "unchanged job keeps its match"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pipeline/test_ingest.py -v`
Expected: FAIL — the j1/user_a match is still `new`.

- [ ] **Step 3: Implement**

In `src/jobscout/pipeline/ingest.py`, add to the imports:
```python
from sqlmodel import Session, col, select, update

from jobscout.models import Job, Match
```
and in `upsert_jobs`, right after the two `stats.*_ids` assignments and before `session.commit()`:
```python
    _mark_matches_stale(session, stats.changed_ids)
```
Add the helper above `upsert_jobs`:
```python
def _mark_matches_stale(session: Session, job_ids: list[int]) -> None:
    """A changed description invalidates every score derived from it — except a user's own no."""
    for start in range(0, len(job_ids), _LOOKUP_CHUNK):
        chunk = job_ids[start : start + _LOOKUP_CHUNK]
        session.exec(  # type: ignore[call-overload]
            update(Match)
            .where(col(Match.job_id).in_(chunk), Match.status != "dismissed")
            .values(status="stale")
        )
```
(The `# type: ignore[call-overload]` is for SQLModel's `Session.exec` overloads not covering `update`; drop it if mypy does not complain.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/pipeline -q` → all pass. `uv run mypy src` → Success.

- [ ] **Step 5: Lint and commit**

```powershell
uv run ruff check . ; uv run ruff format .
git add src/jobscout/pipeline/ingest.py tests/pipeline/test_ingest.py
git commit -m "feat: mark matches stale when a job's text changes" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: `update_preferences` reports changes and clears the profile embedding

**Files:**
- Modify: `src/jobscout/pipeline/users.py`
- Modify: `tests/pipeline/test_users.py`

**Interfaces:**
- Produces: `update_preferences(session, user_id, changes) -> tuple[UserPreferences, frozenset[str]]` (preferences, names of fields that actually changed value); `MATCHING_RELEVANT_FIELDS: frozenset[str]` = `{"titles", "seniority", "required_skills", "nice_to_have_skills", "min_salary", "profile_summary"}`.
- **Breaking change:** every existing caller must unpack the tuple. Callers today: `api/routers/preferences.py` (Task 11 rewires it via `save_preferences`; until then update it in this task to `prefs, _ = update_preferences(...)`) and the tests in `tests/pipeline/test_users.py`.

- [ ] **Step 1: Write the failing tests** (append to `tests/pipeline/test_users.py`)

```python
def test_update_preferences_reports_changed_fields(session):
    user = get_or_create_default_user(session)
    _, changed = update_preferences(session, user.id, {"titles": ["AI Engineer"]})
    assert changed == frozenset({"titles"})

    _, changed = update_preferences(session, user.id, {"titles": ["AI Engineer"]})
    assert changed == frozenset(), "same value is not a change"


def test_profile_summary_change_clears_the_profile_embedding(session):
    user = get_or_create_default_user(session)
    prefs, _ = update_preferences(session, user.id, {"profile_summary": "first"})
    prefs.profile_embedding = b"\x00\x01\x02\x03"
    session.add(prefs)
    session.commit()

    prefs, changed = update_preferences(session, user.id, {"profile_summary": "second"})

    assert "profile_summary" in changed
    assert prefs.profile_embedding is None


def test_unrelated_change_keeps_the_profile_embedding(session):
    user = get_or_create_default_user(session)
    prefs, _ = update_preferences(session, user.id, {"profile_summary": "first"})
    prefs.profile_embedding = b"\x00\x01\x02\x03"
    session.add(prefs)
    session.commit()

    prefs, _ = update_preferences(session, user.id, {"min_score_to_notify": 80})

    assert prefs.profile_embedding == b"\x00\x01\x02\x03"


def test_matching_relevant_fields_are_declared():
    from jobscout.pipeline.users import MATCHING_RELEVANT_FIELDS

    assert MATCHING_RELEVANT_FIELDS == frozenset(
        {
            "titles",
            "seniority",
            "required_skills",
            "nice_to_have_skills",
            "min_salary",
            "profile_summary",
        }
    )
```

Update the four existing tests in that file that call `update_preferences` to unpack: `prefs, _ = update_preferences(...)`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pipeline/test_users.py -v`
Expected: FAIL — `ImportError: cannot import name 'MATCHING_RELEVANT_FIELDS'` and tuple-unpacking errors.

- [ ] **Step 3: Implement**

In `src/jobscout/pipeline/users.py` add the constant near the top:
```python
MATCHING_RELEVANT_FIELDS: frozenset[str] = frozenset(
    {
        "titles",
        "seniority",
        "required_skills",
        "nice_to_have_skills",
        "min_salary",
        "profile_summary",
    }
)
"""Changing any of these invalidates existing scores; see pipeline.run.save_preferences."""
```
and replace the tail of `update_preferences` (from `prefs = get_preferences(...)`):
```python
    prefs = get_preferences(session, user_id)
    changed = frozenset(
        field for field, value in changes.items() if getattr(prefs, field) != value
    )
    for field, value in changes.items():
        setattr(prefs, field, value)
    if "profile_summary" in changed:
        prefs.profile_embedding = None  # the stored vector described the old summary
    session.add(prefs)
    session.commit()
    session.refresh(prefs)
    return prefs, changed
```
and its signature/docstring:
```python
def update_preferences(
    session: Session, user_id: int, changes: dict[str, Any]
) -> tuple[UserPreferences, frozenset[str]]:
    """Apply a partial update; return the row and the names of fields whose value changed."""
```
In `src/jobscout/api/routers/preferences.py::put_preferences`, change the call to `prefs, _ = update_preferences(session, cast(int, user.id), changes)`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -q` → all pass. `uv run mypy src` → Success.

- [ ] **Step 5: Lint and commit**

```powershell
uv run ruff check . ; uv run ruff format .
git add src/jobscout/pipeline/users.py src/jobscout/api/routers/preferences.py tests/pipeline/test_users.py
git commit -m "feat: report changed preference fields and drop the stale profile vector" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Backfill and `save_preferences`

**Files:**
- Create: `src/jobscout/pipeline/backfill.py`, `tests/pipeline/test_backfill.py`
- Modify: `src/jobscout/pipeline/run.py`

**Interfaces:**
- Consumes: `run_match`, `MatchRun` (Task 7); `update_preferences`, `MATCHING_RELEVANT_FIELDS` (Task 9); `Match` (Task 4).
- Produces:
  - `backfill_matches(session, settings, user_id, window_days: int | None = None) -> MatchRun` — like `run_match`, restricted to jobs first seen within the window.
  - `save_preferences(session, settings, user_id, changes) -> tuple[UserPreferences, MatchRun]` in `pipeline/run.py`.

- [ ] **Step 1: Write the failing tests**

`tests/pipeline/test_backfill.py`:
```python
from datetime import timedelta

from langchain_core.embeddings import DeterministicFakeEmbedding
from sqlmodel import select

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps
from jobscout.models import Job, Match
from jobscout.models.base import utcnow
from jobscout.pipeline.backfill import backfill_matches
from jobscout.pipeline.run import save_preferences
from jobscout.pipeline.users import get_or_create_default_user, update_preferences
from tests.matching.fakes import CountingChatModel

DIM = 8


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _deps(chat: CountingChatModel) -> GraphDeps:
    return GraphDeps(
        chat=chat,  # type: ignore[arg-type]
        embed=DeterministicFakeEmbedding(size=DIM),
        threshold=-1.0,
        model_name="fake-model",
    )


def _add_job(session, external_id: str, days_ago: int = 0) -> Job:
    seen = utcnow() - timedelta(days=days_ago)
    job = Job(
        source="t",
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        remote=True,
        url=f"https://x/{external_id}",
        description="Python LLM work.",
        content_hash=f"h-{external_id}",
        first_seen_at=seen,
        last_seen_at=seen,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_backfill_only_covers_the_window(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    _add_job(session, "recent", days_ago=1)
    _add_job(session, "ancient", days_ago=99)
    chat = CountingChatModel()

    result = backfill_matches(session, _settings(), user.id, window_days=30, deps=_deps(chat))

    assert result.evaluated == 1
    matched_ids = {m.job_id for m in session.exec(select(Match)).all()}
    recent = session.exec(select(Job).where(Job.external_id == "recent")).one()
    assert matched_ids == {recent.id}


def test_save_preferences_stales_and_backfills(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    job = _add_job(session, "a")
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, score=50, status="new"))
    session.commit()
    chat = CountingChatModel()

    prefs, run = save_preferences(
        session,
        _settings(),
        user.id,
        {"required_skills": ["Python"]},
        deps=_deps(chat),
    )

    assert prefs.required_skills == ["Python"]
    assert run.evaluated == 1, "the staled match was re-evaluated"
    assert session.exec(select(Match)).one().status == "new"


def test_save_preferences_ignores_irrelevant_changes(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    job = _add_job(session, "a")
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, score=50, status="seen"))
    session.commit()
    chat = CountingChatModel()

    _, run = save_preferences(
        session, _settings(), user.id, {"min_score_to_notify": 90}, deps=_deps(chat)
    )

    assert (run.evaluated, chat.calls) == (0, 0)
    assert session.exec(select(Match)).one().status == "seen"


def test_save_preferences_never_stales_dismissed(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    job = _add_job(session, "a")
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, status="dismissed"))
    session.commit()
    chat = CountingChatModel()

    _, run = save_preferences(
        session, _settings(), user.id, {"titles": ["AI Engineer"]}, deps=_deps(chat)
    )

    assert run.evaluated == 0
    assert session.exec(select(Match)).one().status == "dismissed"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pipeline/test_backfill.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jobscout.pipeline.backfill'`.

- [ ] **Step 3: Implement `backfill.py`**

```python
"""Re-scan history for one user: jobs first seen inside the window that have no fresh match."""

from datetime import timedelta

from sqlmodel import Session

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps
from jobscout.models.base import utcnow
from jobscout.pipeline.matching import MatchRun, run_match


def backfill_matches(
    session: Session,
    settings: Settings,
    user_id: int,
    window_days: int | None = None,
    deps: GraphDeps | None = None,
) -> MatchRun:
    days = window_days if window_days is not None else settings.backfill_window_days
    cutoff = utcnow() - timedelta(days=days)
    return run_match(session, settings, user_id, deps=deps, first_seen_after=cutoff)
```

This needs one addition to `run_match` (Task 7): a keyword-only parameter `first_seen_after: datetime | None = None`, passed through to `select_candidates`, which adds `Job.first_seen_at >= first_seen_after` to its query when set. Add the parameter to both signatures now:
```python
def select_candidates(
    session: Session,
    prefs: UserPreferences,
    user_id: int,
    first_seen_after: datetime | None = None,
) -> list[Job]:
    ...
    statement = select(Job).where(col(Job.is_active).is_(True))
    if first_seen_after is not None:
        statement = statement.where(Job.first_seen_at >= first_seen_after)
    jobs = session.exec(statement).all()
```

- [ ] **Step 4: Implement `save_preferences` in `pipeline/run.py`**

```python
def save_preferences(
    session: Session,
    settings: Settings,
    user_id: int,
    changes: dict[str, Any],
    deps: GraphDeps | None = None,
) -> tuple[UserPreferences, MatchRun]:
    """Apply preference changes, invalidate what they affect, and backfill within the cap."""
    prefs, changed = update_preferences(session, user_id, changes)
    if not (changed & MATCHING_RELEVANT_FIELDS):
        return prefs, MatchRun()

    session.exec(  # type: ignore[call-overload]
        update(Match)
        .where(Match.user_id == user_id, Match.status != "dismissed")
        .values(status="stale")
    )
    session.commit()
    return prefs, backfill_matches(session, settings, user_id, deps=deps)
```
with the imports it needs (`Any`, `update`, `Match`, `UserPreferences`, `MatchRun`, `GraphDeps`, `backfill_matches`, `update_preferences`, `MATCHING_RELEVANT_FIELDS`).

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/pipeline -v` → all pass; then `uv run pytest -q` and `uv run mypy src`.

- [ ] **Step 6: Lint and commit**

```powershell
uv run ruff check . ; uv run ruff format .
git add src/jobscout/pipeline/backfill.py src/jobscout/pipeline/run.py src/jobscout/pipeline/matching.py tests/pipeline/test_backfill.py
git commit -m "feat: backfill matches when preferences change" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: `GET /matches`, `MatchRead`, and the current-user-id dependency

**Files:**
- Create: `src/jobscout/api/routers/matches.py`, `tests/api/test_matches.py`
- Modify: `src/jobscout/api/deps.py`, `src/jobscout/api/schemas.py`, `src/jobscout/api/app.py`, `src/jobscout/api/routers/jobs.py`, `src/jobscout/api/routers/preferences.py`, `src/jobscout/cli.py`

**Interfaces:**
- Produces: `deps.get_current_user_id(user) -> int`; `MatchRead`; `GET /matches`.
- Removes: the four `cast(int, user.id)` call sites.

- [ ] **Step 1: Write the failing tests**

`tests/api/test_matches.py`:
```python
from sqlmodel import select

from jobscout.models import Job, Match, User


def _job(session, external_id="a", active=True) -> Job:
    job = Job(
        source="t",
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        remote=True,
        url=f"https://x/{external_id}",
        description="d",
        content_hash=f"h-{external_id}",
        is_active=active,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _bootstrap_user(client, session) -> User:
    client.get("/preferences")  # creates the default user
    return session.exec(select(User)).one()


def test_matches_empty(client):
    assert client.get("/matches").json() == []


def test_matches_returns_scored_rows_newest_score_first(client, session):
    user = _bootstrap_user(client, session)
    low = _job(session, "low")
    high = _job(session, "high")
    session.add(Match(job_id=low.id, user_id=user.id, similarity=0.5, score=40, status="new"))
    session.add(
        Match(
            job_id=high.id,
            user_id=user.id,
            similarity=0.8,
            score=90,
            reasoning="Strong.",
            matched_skills=["Python"],
            status="new",
        )
    )
    session.commit()

    body = client.get("/matches").json()

    assert [m["score"] for m in body] == [90, 40]
    assert body[0]["job"]["external_id"] == "high"
    assert body[0]["matched_skills"] == ["Python"]
    assert "raw" not in body[0]["job"] and "embedding" not in body[0]["job"]


def test_matches_hides_inactive_jobs(client, session):
    user = _bootstrap_user(client, session)
    job = _job(session, "gone", active=False)
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, score=95, status="new"))
    session.commit()

    assert client.get("/matches").json() == []


def test_matches_filters_by_min_score_and_status(client, session):
    user = _bootstrap_user(client, session)
    a = _job(session, "a")
    b = _job(session, "b")
    session.add(Match(job_id=a.id, user_id=user.id, similarity=0.5, score=40, status="new"))
    session.add(Match(job_id=b.id, user_id=user.id, similarity=0.9, score=95, status="saved"))
    session.commit()

    assert [m["score"] for m in client.get("/matches", params={"min_score": 50}).json()] == [95]
    assert [m["job"]["external_id"] for m in client.get(
        "/matches", params={"status": "saved"}
    ).json()] == ["b"]


def test_matches_excludes_unscored_low_rows(client, session):
    user = _bootstrap_user(client, session)
    job = _job(session, "a")
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.1, score=None, status="low"))
    session.commit()

    assert client.get("/matches").json() == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/api/test_matches.py -v`
Expected: FAIL — 404 on `/matches`.

- [ ] **Step 3: Add the dependency and the schema**

`src/jobscout/api/deps.py`, append:
```python
def get_current_user_id(user: Annotated[User, Depends(get_current_user)]) -> int:
    """The current user's id, non-optional. Auth (stage 6) replaces get_current_user only."""
    assert user.id is not None, "a persisted user always has an id"
    return user.id
```

`src/jobscout/api/schemas.py`, append:
```python
class MatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    similarity: float
    score: int | None
    reasoning: str | None
    matched_skills: list[str]
    missing_skills: list[str]
    red_flags: list[str]
    status: str
    llm_model: str | None
    job: JobRead
```

- [ ] **Step 4: Add the router and register it**

`src/jobscout/api/routers/matches.py`:
```python
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, col, select

from jobscout.api.deps import get_current_user_id, get_session
from jobscout.api.schemas import JobRead, MatchRead
from jobscout.models import Job, Match

router = APIRouter(prefix="/matches", tags=["matches"])


@router.get("", response_model=list[MatchRead])
def read_matches(
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
    min_score: Annotated[int, Query(ge=0, le=100)] = 0,
    status: Annotated[str | None, Query(description="Filter by match status.")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[MatchRead]:
    """Scored matches for the current user, best first. Inactive jobs are hidden."""
    statement = (
        select(Match, Job)
        .join(Job, col(Match.job_id) == col(Job.id))
        .where(
            Match.user_id == user_id,
            col(Job.is_active).is_(True),
            col(Match.score).is_not(None),
            col(Match.score) >= min_score,
        )
        .order_by(col(Match.score).desc(), col(Match.similarity).desc())
    )
    if status is not None:
        statement = statement.where(Match.status == status)

    rows = session.exec(statement).all()[:limit]
    return [
        MatchRead(
            id=match.id or 0,
            similarity=match.similarity,
            score=match.score,
            reasoning=match.reasoning,
            matched_skills=match.matched_skills,
            missing_skills=match.missing_skills,
            red_flags=match.red_flags,
            status=match.status,
            llm_model=match.llm_model,
            job=JobRead.model_validate(job),
        )
        for match, job in rows
    ]
```

In `src/jobscout/api/app.py`: `from jobscout.api.routers import jobs, matches, preferences` and `application.include_router(matches.router)`.

- [ ] **Step 5: Remove the four casts**

In `api/routers/jobs.py` and `api/routers/preferences.py`, replace the `user: Annotated[User, Depends(get_current_user)]` parameter with `user_id: Annotated[int, Depends(get_current_user_id)]`, use `user_id` directly, and drop the now-unused `cast` and `User` imports. In `cli.py::jobs`, replace `cast(int, user.id)` with a local `user_id = user.id` guarded by `assert user.id is not None` (or keep `get_or_create_default_user` and add the assert), and drop the `cast` import if unused.

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest -q` → all pass, no warnings. `uv run mypy src` → Success.

- [ ] **Step 7: Lint and commit**

```powershell
uv run ruff check . ; uv run ruff format .
git add src/jobscout/api src/jobscout/cli.py tests/api/test_matches.py
git commit -m "feat: add GET /matches and a current-user-id dependency" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: CLI `match` and `matches`

**Files:**
- Modify: `src/jobscout/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_match`, `MatchRun` (Task 7); `MissingProviderError` (Task 3).
- Produces: `jobscout match [--limit N] [--dry-run]`, `jobscout matches [--min-score N] [--limit N]`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_cli.py`)

```python
def test_match_without_provider_key_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_settings", lambda: _settings(tmp_path))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
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
```

Add the imports these need at the top of `tests/test_cli.py`: `from jobscout.db import get_engine, init_db`, `from jobscout.models import Job, Match`, `from jobscout.pipeline.users import get_or_create_default_user, update_preferences`, `from sqlmodel import Session`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `No such command 'match'`.

- [ ] **Step 3: Implement**

In `src/jobscout/cli.py`, add the imports (`MissingProviderError`, `run_match`, `Match`, `Job`, `col`, `select`) and the two commands after `jobs`:
```python
@app.command()
def match(
    limit: Annotated[int | None, typer.Option(help="Evaluate at most this many jobs.")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be evaluated; call no LLM.")
    ] = False,
) -> None:
    """Score the best unmatched jobs against your profile."""
    settings = get_settings()
    with _session() as session:
        user = get_or_create_default_user(session)
        assert user.id is not None
        try:
            result = run_match(session, settings, user.id, limit=limit, dry_run=dry_run)
        except MissingProviderError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=2) from exc

    if result.error:
        typer.echo(result.error)
        return
    if dry_run:
        if not result.previewed:
            typer.echo(f"Nothing to evaluate ({result.candidates} candidates).")
            return
        typer.echo(f"Would evaluate {len(result.previewed)} of {result.candidates} candidates:")
        for _job_id, similarity, title in result.previewed:
            typer.echo(f"  {similarity:.3f}  {title}")
        return
    typer.echo(
        f"candidates={result.candidates} evaluated={result.evaluated} "
        f"skipped_low={result.skipped_low} errors={len(result.errors)}"
    )
    for message in result.errors:
        typer.echo(f"  ERROR {message}", err=True)


@app.command()
def matches(
    min_score: Annotated[int, typer.Option(help="Only show matches at or above this score.")] = 0,
    limit: Annotated[int, typer.Option(help="Max rows to show.")] = 20,
) -> None:
    """List scored matches, best first."""
    with _session() as session:
        user = get_or_create_default_user(session)
        statement = (
            select(Match, Job)
            .join(Job, col(Match.job_id) == col(Job.id))
            .where(
                Match.user_id == user.id,
                col(Job.is_active).is_(True),
                col(Match.score).is_not(None),
                col(Match.score) >= min_score,
            )
            .order_by(col(Match.score).desc())
        )
        rows = session.exec(statement).all()[:limit]
        if not rows:
            typer.echo("No matches yet. Run `jobscout match` after setting your profile summary.")
            return
        for match_row, job in rows:
            typer.echo(f"[{match_row.score}] {job.title} — {job.company}")
            if match_row.reasoning:
                typer.echo(f"    {match_row.reasoning}")
            typer.echo(f"    {job.url}")
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_cli.py -v` → all pass. `uv run pytest -q`, `uv run mypy src`.

- [ ] **Step 5: Lint and commit**

```powershell
uv run ruff check . ; uv run ruff format .
git add src/jobscout/cli.py tests/test_cli.py
git commit -m "feat: add the match and matches CLI commands" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: Live check, calibration and docs

**Files:**
- Create: `tests/integration/test_matching_live.py`
- Modify: `README.md`, `CLAUDE.md`, `docs/superpowers/specs/2026-09-22-stage-2b-matching-design.md`

**Interfaces:** none; verification and documentation.

- [ ] **Step 1: Write the opt-in live test**

`tests/integration/test_matching_live.py`:
```python
"""Hits the real provider. Run explicitly: `uv run pytest -m integration`.

Needs GOOGLE_API_KEY (or the configured provider's key) and jobs in the database.
"""

import os

import pytest
from sqlmodel import Session, col, select

from jobscout.config import get_settings
from jobscout.db import get_engine, init_db
from jobscout.matching.prompts import job_text, profile_text
from jobscout.matching.llm import chat_model, embeddings
from jobscout.matching.schemas import EvaluationResult
from jobscout.matching.vectors import cosine
from jobscout.models import Job
from jobscout.pipeline.users import get_or_create_default_user, update_preferences

pytestmark = pytest.mark.integration

PROFILE = "Junior AI engineer. Python, FastAPI, LLM applications, LangGraph. Remote, Europe."


@pytest.fixture
def live_session():
    settings = get_settings()
    if not os.environ.get("GOOGLE_API_KEY") and settings.llm_provider == "google":
        pytest.skip("GOOGLE_API_KEY not set")
    engine = get_engine(settings)
    init_db(engine)
    with Session(engine) as session:
        yield session


def test_live_evaluation_and_similarity_distribution(live_session, capsys):
    settings = get_settings()
    jobs = live_session.exec(
        select(Job).where(col(Job.is_active).is_(True)).limit(30)
    ).all()
    if not jobs:
        pytest.skip("no jobs in the database; run `jobscout fetch` first")

    user = get_or_create_default_user(live_session)
    prefs, _ = update_preferences(live_session, user.id, {"profile_summary": PROFILE})

    embedder = embeddings(settings)
    profile_vector = embedder.embed_query(profile_text(prefs))
    job_vectors = embedder.embed_documents([job_text(job) for job in jobs])
    similarities = sorted(
        (cosine(vector, profile_vector), job.title)
        for vector, job in zip(job_vectors, jobs, strict=True)
    )

    with capsys.disabled():
        print(f"\nembedding dim: {len(profile_vector)}  model: {settings.embedding_model}")
        print(f"min={similarities[0][0]:.3f}  max={similarities[-1][0]:.3f}")
        print("top 5:")
        for score, title in reversed(similarities[-5:]):
            print(f"  {score:.3f}  {title}")
        print("bottom 3:")
        for score, title in similarities[:3]:
            print(f"  {score:.3f}  {title}")

    best_title = similarities[-1][1]
    best_job = next(job for job in jobs if job.title == best_title)
    structured = chat_model(settings).with_structured_output(EvaluationResult)
    evaluation = structured.invoke(
        [("system", "Score the fit 0-100."), ("human", f"{PROFILE}\n\n{job_text(best_job)}")]
    )

    assert isinstance(evaluation, EvaluationResult)
    assert 0 <= evaluation.score <= 100
    assert evaluation.reasoning.strip()
```

- [ ] **Step 2: Verify default deselection, then run it live**

Run: `uv run pytest -q` — the live test must be deselected (count unchanged, "deselected" in the summary).
Run: `uv run jobscout fetch` (populates the DB), then `uv run pytest -m integration -v -s`.
Expected: the Arbeitnow live test plus this one pass. **Record the printed embedding dimension and similarity range in the report.** If `gemini-embedding-001` or `gemini-3.5-flash` errors with a model-not-found, use the name the API accepts, update `config.py`, `.env.example`, the spec §5.5 table and the plan's Global Constraints, and say so in the report.

- [ ] **Step 3: Calibrate the threshold if the data says so**

If the printed distribution shows the *lowest* observed similarity already above `0.35` (so the floor never fires) or a clear gap between relevant and irrelevant jobs, set `similarity_threshold` to a value inside that gap in `config.py` and `.env.example`, and note the observed numbers in a comment. If the distribution is inconclusive, leave `0.35` and say so.

- [ ] **Step 4: Manual end-to-end check**

Run: `uv run jobscout match --dry-run` (shows ranked candidates, no LLM call), then `uv run jobscout match`, then `uv run jobscout matches --min-score 60`, then `uv run jobscout serve` and `GET /matches?min_score=60` in `/docs`. Run `uv run jobscout match` a second time and confirm `evaluated=0` (idempotent). Paste the first lines of each in the report. Stop the server.

- [ ] **Step 5: Update the docs**

`README.md` — after the Quick start block, add:
```markdown
## Matching (AI)

```bash
cp .env.example .env          # set LLM_PROVIDER and your provider key
uv run jobscout match --dry-run   # ranked candidates, no LLM call
uv run jobscout match             # score them (bounded by MAX_LLM_EVALUATIONS_PER_RUN)
uv run jobscout matches --min-score 70
```

Each match carries a 0–100 score, a written justification, matched and missing skills, and
red flags. A cosine prefilter over cached embeddings decides what is worth an LLM call, so a
run costs a bounded number of requests. Without a provider key, everything except matching
still works.
```
and add `| GET | `/matches` | Scored matches, best first (`?min_score=`, `?status=`, `?limit=`) |` to the API table.

`CLAUDE.md` — **Current state** becomes: "Stages 0, 1, 2a and 2b are implemented (see the plans in `docs/superpowers/plans/`). Next is stage 3 (scheduler + inactive marking)." Add to **Commands**: "- `uv run jobscout match|matches` — run the matching graph / list scored matches (needs a provider key)."

Spec §5.5: if Step 2 or 3 changed a default, update the table there too.

- [ ] **Step 6: Final verification and commit**

Run: `uv run ruff check . ; uv run ruff format --check . ; uv run mypy src ; uv run pytest -q`
```powershell
git add tests/integration README.md CLAUDE.md docs/superpowers/specs src/jobscout/config.py .env.example
git commit -m "docs: document matching and add the live calibration test" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-review against the spec

- **§2 decisions → tasks:** deterministic gate (T7 `select_candidates`), `low` rows (T7), stale on preference change (T9+T10), vectors (T2), top-K vs. graph (T6+T7), missing key (T3+T12), structured output (T5+T6), match visibility (T11), providers (T3), one plan (this document). ✔
- **§3 components:** every file in the spec's tree has a task. ✔
- **§4 data model:** T4, including the two status frozensets and the `dismissed` rule (tested in T7 and T10). ✔
- **§5 behavior:** 5.1 run_match → T7 (+ window parameter in T10); 5.2 graph → T6; 5.3 save_preferences → T9+T10; 5.4 ingest stale-marking → T8; 5.5 config → T1 (calibrated in T13). ✔
- **§6 interfaces:** CLI → T12; API → T11. ✔
- **§7 testing:** every listed case has a test — prefilter-zero-LLM (T6, T7), top-K cap (T7), stale vs. dismissed (T7, T10), isolated failure (T7), save_preferences (T10), ingest stale (T8), inactive hidden (T11), missing key (T3, T12), integration (T13). ✔
- **§9 done-when:** T13 steps 2, 4 and 6. ✔
- **Type/name consistency:** `GraphDeps(chat, embed, threshold, model_name)` identical in T6, T7, T10 tests; `MatchRun` fields identical in T7, T10, T12; `run_match(session, settings, user_id, limit, dry_run, deps, first_seen_after)` — the last parameter is added in T10 and used only there; `update_preferences` returns a tuple from T9 on, and T10's `save_preferences` plus T9's router edit are the only callers; `get_current_user_id` used in T11 only; `MATCHING_RELEVANT_FIELDS` defined in T9, consumed in T10.
- **Known plan risk, flagged for the executor:** T6's `build_graph` returns `object` because the installed LangGraph's `CompiledStateGraph` generic arity is unverified; T7 therefore calls `graph.invoke(...)` behind a `# type: ignore[attr-defined]`. If the concrete return type annotates cleanly under `--strict`, use it in both places and drop the ignore.
- **Test counts:** 96 → T1 +2 = 98 → T2 +5 = 103 → T3 +4 = 107 → T4 +3 = 110 → T5 +4 = 114 → T6 +4 = 118 → T7 +10 = 128 → T8 +1 = 129 → T9 +4 = 133 → T10 +4 = 137 → T11 +5 = 142 → T12 +4 = 146 (plus one deselected integration test).

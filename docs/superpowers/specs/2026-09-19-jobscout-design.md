# JobScout — Design Spec

**Date:** 2026-09-19
**Status:** Approved for planning
**Supersedes:** open questions in `job-radar-contexto.md` (sections 3, 8)

## 1. Purpose

JobScout is an open-source Python agent that continuously collects tech job postings from public job-board APIs, semantically matches them against a user's profile using embeddings plus an LLM that explains its score, and notifies the user of good matches. It is the centerpiece of a junior AI Engineer portfolio: it must demonstrate LangGraph, embedding-based matching, multi-provider LLM integration, and solid engineering practice, while solving a real problem well enough that others use and contribute to it.

## 2. Decisions

| Topic | Decision | Rationale |
|---|---|---|
| Name | `jobscout` (GitHub repo under the author's namespace; not published to PyPI under this name — that name is taken by a similar project) | Author's choice, accepting brand collision |
| Users in v1 | Single fixed user, but every table and endpoint is keyed by `user_id` | Avoids a large refactor later without paying for auth now |
| Interface in v1 | FastAPI + Typer CLI; no web UI until the core is stable | Keeps the backend free of UI coupling |
| When AI enters | Stage 2, right after collection works | The portfolio differentiator arrives early, iterated on real data |
| LLM/embeddings | LangChain chat-model and embeddings abstractions, provider chosen by env (`LLM_PROVIDER`, `LLM_MODEL`, `EMBEDDING_MODEL`) | LangGraph already brings LangChain; multi-provider for free; contributors run with whatever key they have |
| Database | SQLModel; SQLite by default, PostgreSQL via `DATABASE_URL` | No Docker needed to develop; embeddings stored as bytes until vector search is actually needed |
| First source | Arbeitnow | Public API, no key, Europe/remote focus, clean JSON |
| Scheduler | APScheduler inside the FastAPI lifespan | One process, no Redis; sufficient for single-user through dozens of users |
| LangGraph scope | Only the per-job matching graph, with typed state and a conditional edge that skips the LLM for low-similarity jobs | Real use of the graph without forcing it onto linear plumbing |
| Tooling | `uv`, src-layout, `ruff`, `pytest`, GitHub Actions | Standard for new OSS Python projects |
| Repo layout | Single Python package at repo root (`src/jobscout/`); frontend joins later | No empty `frontend/` folder for weeks |
| Frontend (stage 6) | Reflex | Keeps the stack in Python |
| Notification channel | Deferred to stage 4; a `Notifier` protocol is defined so the channel is pluggable | Decide with real matches in hand |
| Distribution | Hybrid: built for self-hosting; a public demo instance with per-user quotas and optional BYOK (bring your own LLM key) in stage 7 | Visibility for the portfolio with predictable cost |
| License | MIT | |
| Language | English for code, comments, and main README; README also in pt-BR and es | |

## 3. Roadmap

Every stage ends with something that runs end to end.

| Stage | Deliverable | Done when |
|---|---|---|
| 0 Foundation | `git init`, `uv init` (src-layout), `pyproject.toml` with ruff + pytest, GitHub Actions (lint + tests), MIT license, README skeleton (EN), `.env.example`, updated `CLAUDE.md` | CI is green on an empty package |
| 1 Vertical slice, no AI | SQLModel models + SQLite; `JobSource` protocol + `ArbeitnowSource`; upsert ingest with dedup and liveness tracking; deterministic pre-filter (work mode/region/keywords); CLI `fetch`, `jobs`; API `GET /jobs`, `GET/PUT /preferences`. Operator config (env) strictly separated from user preferences (DB) | `uv run jobscout fetch` stores real jobs in SQLite and they appear in Swagger |
| 2 AI matching | LangGraph matching graph; `Match` model; provider factory from settings; backfill on preference save; CLI `match`; API `GET /matches`; tests with fake LLM/embeddings | Score + reasoning on real jobs; fake-LLM tests pass, including the "prefilter rejects, LLM not called" path |
| 3 Continuous run | APScheduler in lifespan calling `run_pipeline(user_id)`; only new jobs are matched; jobs unseen for N days marked inactive; interval configurable | Left running for an hour, new jobs appear on their own |
| 4 Notification | `Notifier` protocol + first channel (Telegram, e-mail, push/PWA — decided at that time); `min_score_to_notify` threshold | A notification arrives |
| 5 Multi-source | RemoteOK, Adzuna (key), Jooble, The Muse — one PR each; "How to add a source" guide; generic contract test runs against every registered source | At least 3 sources live |
| 6 Product | Reflex UI (config wizard, dashboard); real auth and multi-user; Postgres in `docker-compose.yml`; i18n (READMEs + UI, en/pt/es) | Someone signs up and uses it without the author |
| 7 Public demo | `Usage` quotas per user, BYOK (encrypted per-user LLM key), deploy of a demo instance, README link | A recruiter clicks the link and sees it working |

**Starting point:** stage 0 plus the `JobSource` protocol with Arbeitnow via TDD, in the same session. Leave the session with CI green and real jobs in the database.

## 4. Architecture

Package `src/jobscout/`. Dependencies point only "downward".

```
config.py        Settings (pydantic-settings) — OPERATOR config from env:
                 DATABASE_URL, LLM_PROVIDER, LLM_MODEL, EMBEDDING_MODEL, provider keys,
                 SCHEDULER_INTERVAL_MINUTES, INACTIVE_AFTER_DAYS
models/          SQLModel tables: User, UserPreferences, Job, Match (stage 7: Usage)
db.py            engine + session factory; SQLite by default, Postgres via DATABASE_URL
sources/         base.py   Protocol JobSource { name: str; fetch(prefs) -> list[RawJob] }
                 arbeitnow.py, remoteok.py, ...  HTTP + parsing to RawJob only; no DB access
                 registry.py  active sources (from settings)
pipeline/        ingest.py    fetch all sources -> normalize -> upsert Job (dedup + liveness + content hash)
                 backfill.py  backfill_matches(user_id, window_days)
                 run.py       run_ingest(session, settings) [global]; run_pipeline = ingest -> match new/changed jobs per user -> notify
                 plain Python; no LangGraph here
matching/        llm.py        factory: chat model + embeddings from Settings
                 embeddings.py embed profile and job text
                 schemas.py    MatchState (graph state), EvaluationResult (LLM structured output)
                 prompts.py
                 graph.py      LangGraph StateGraph, one run per (job, user)
notifiers/       base.py  Protocol Notifier { send(match) }; implementations from stage 4
scheduler.py     APScheduler wired into FastAPI lifespan (stage 3)
api/             FastAPI app; routers jobs, preferences, matches; deps.py with get_session, get_current_user
cli.py           Typer: fetch, match, run, jobs, serve
```

**Dependency rules**
- `sources` knows nothing about the database.
- `matching` knows nothing about HTTP or sources.
- `pipeline` is the only module that composes the others.
- `api` and `cli` are thin shells over `pipeline`; no business logic.
- `notifiers` depend only on `models`.

**Current user before auth:** `api/deps.py::get_current_user()` returns the fixed user (id 1, created at startup if missing). In stage 6 only this function changes.

**Operator vs. user config:** anything that identifies *who runs the instance* (LLM keys, database, notifier credentials, intervals) lives in `Settings`/env. Anything that describes *what a person wants* lives in `UserPreferences`. These never mix; this is a prerequisite for the hosted demo.

## 5. Data flow

1. `Source.fetch(query)` returns `RawJob` objects (Pydantic; already normalized to a common shape). *(Amended 2026-09-21, stage 2a:)* ingest is instance-global; sources return everything they fetch and never drop results based on `query`. `SearchQuery` only parameterizes APIs that require server-side search (stage 5 builds it from the union of all users' keywords). User filtering happens in `pipeline/filters.py` and, from stage 2b, in the matching graph.
2. `ingest` upserts each `RawJob` into `Job`, keyed by `(source, external_id)`:
   - new → insert with `first_seen_at = last_seen_at = now`, `is_active = True`, `content_hash`
   - known → refresh all metadata fields (`company, location, remote, url, salary_*, tags, posted_at, raw`), set `last_seen_at`, reactivate *(amended 2026-09-21, stage 2a)*
   - known and `content_hash` (title + description) differs → also update title/description, clear `embedding`, mark existing `Match` rows `stale` (stage 2b)
   - `UpsertStats` reports `created_ids` / `changed_ids` so downstream matching targets exactly those rows
3. For each new (or stale) `Job` × each user, a deterministic pre-filter (`pipeline/filters.py`: work mode, region, hard keyword exclusions from preferences) drops obvious non-candidates without writing anything; the rest go through `matching.graph`, which writes a `Match`. In stage 1, before the graph exists, this filter alone decides what `jobs` lists.
4. `Notifier.send(match)` fires when `match.score >= prefs.min_score_to_notify` and `status == new`.
5. Periodically (stage 3), jobs with `last_seen_at` older than `INACTIVE_AFTER_DAYS` are marked `is_active = False`. Matching and backfill consider only active jobs.
6. When preferences are created or updated, `backfill_matches(user_id, BACKFILL_WINDOW_DAYS)` runs the graph over active jobs first seen within the window that have no `Match` for that user yet.

## 6. Matching graph (stage 2)

State `MatchState`: `job_id`, `user_id`, `job_text`, `profile_text`, `job_embedding`, `profile_embedding`, `similarity`, `evaluation: EvaluationResult | None`, `should_notify: bool`.

Nodes and edges:

```
embed_job -> prefilter --(similarity < threshold)--> record_low   -> END
                       --(otherwise)---------------> evaluate -> decide -> END
```

- `embed_job`: computes/loads the job embedding (cached on `Job.embedding`); the profile embedding is cached on `UserPreferences.profile_embedding`.
- `prefilter`: cosine similarity. Below the threshold, `record_low` writes a `Match` with `similarity` and `score = None` and the graph ends without an LLM call. This conditional edge is what keeps cost linear in *good* candidates, not in all jobs.
- `evaluate`: chat model with `with_structured_output(EvaluationResult)`; prompt receives profile text, preferences (titles, seniority, skills, salary, work mode, regions) and the job. Output: `score` (0–100), `reasoning`, `matched_skills`, `missing_skills`, `red_flags`.
- `decide`: sets `should_notify` from the user's threshold.

`EvaluationResult` is a Pydantic model; `Match.llm_model` records which model produced it.

## 7. Data model

All tables have `id`, `created_at`, `updated_at`. Lists are stored as JSON columns.

**User** — `email` (unique), `locale` (`en`|`pt`|`es`). No password until stage 6.

**UserPreferences** (1:1 User) — `user_id`, `titles: list[str]`, `seniority: list[str]`, `work_modes: list[remote|hybrid|onsite]`, `regions: list[str]`, `min_salary: int | None`, `salary_currency: str | None`, `required_skills: list[str]`, `nice_to_have_skills: list[str]`, `profile_summary: str` (free text; source of the profile embedding), `profile_embedding: bytes | None`, `min_score_to_notify: int` (default 70). Stage 7 adds encrypted `llm_api_key` for BYOK.

**Job** (global, not per user) — `source: str`, `external_id: str` (unique together with `source`), `title`, `company`, `location`, `remote: bool`, `url`, `description`, `salary_min`, `salary_max`, `salary_currency` (optional), `tags: list[str]`, `posted_at: datetime | None`, `first_seen_at`, `last_seen_at`, `is_active: bool`, `content_hash: str`, `embedding: bytes | None`, `raw: dict` (original payload, for reprocessing without refetching).

**Match** (unique on `job_id`, `user_id`) — `job_id`, `user_id`, `similarity: float`, `score: int | None` (null when prefilter rejected), `reasoning: str | None`, `matched_skills`, `missing_skills`, `red_flags: list[str]`, `status: new|notified|seen|dismissed|saved|stale`, `llm_model: str | None`.

**Usage** (stage 7) — `user_id`, `date`, `llm_calls`, `jobs_evaluated`.

Non-persisted contracts:
- `RawJob` (what every source returns) — `source`, `external_id`, `title`, `company`, `location`, `remote`, `url`, `description`, `salary_min`, `salary_max`, `salary_currency`, `tags`, `posted_at`, `raw`. Same shape as `Job` minus persistence/liveness fields; `ingest` derives `content_hash` from `title + description`.
- `EvaluationResult` (LLM output) and `MatchState` (graph state) — see section 6.

## 8. Error handling

- A failing source must not abort ingest: each source is fetched in isolation, errors are logged with the source name, and the others proceed. `fetch` reports per-source counts and failures.
- LLM/embedding failures for one job mark nothing and are retried on the next pipeline run (the job simply has no `Match` yet). Structured-output parse failures are logged with the raw response.
- Ingest is idempotent: running twice with the same data changes only `last_seen_at`.
- Settings validation fails fast at startup with a clear message naming the missing variable.
- The API lifespan (`init_db` + default-user bootstrap through `db.get_engine()`) is covered by a test; CLI and API share the same engine seam *(added 2026-09-21, stage 2a)*.

## 9. Testing and CI

- **Sources:** unit tests with recorded JSON fixtures (`tests/fixtures/<source>_sample.json`) and `respx` for HTTP mocking. A generic contract test runs against every source in the registry (returns `RawJob`s, stable `external_id`, required fields present).
- **Pipeline:** in-memory SQLite; asserts dedup, idempotency, liveness fields, content-hash change handling, backfill selection.
- **Matching:** LangChain `FakeEmbeddings` and `FakeListChatModel`; full graph runs without any key, including the path where prefilter rejects and the LLM is never invoked (asserted via a counting fake).
- **API:** `TestClient` with in-memory DB.
- **Integration** tests (real Arbeitnow, real LLM) behind `pytest -m integration`, off by default, not in CI.
- **CI:** GitHub Actions on push/PR — `ruff check`, `ruff format --check`, `pytest`, Python 3.12. `mypy` added in stage 6.
- **Method:** TDD for all logic (sources, ingest, graph, backfill). Shells (CLI, routers) get tests after.

## 10. Out of scope for stages 0–2

Web UI, auth, notifications, scheduler, Postgres/Docker, i18n, quotas, BYOK, vector database. Each has a stage; none is designed further here.

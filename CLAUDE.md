# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

Stages 0, 1 and 2a are implemented (see the plans in `docs/superpowers/plans/`). Next is stage 2b (LangGraph matching). The design source of truth is `docs/superpowers/specs/2026-09-19-jobscout-design.md`; `job-radar-contexto.md` is the original Portuguese brainstorm.

## What the project is

**JobScout**: an open-source Python agent that continuously collects tech job postings from public job-board APIs (never scraping), matches them against a user's profile with embeddings + an LLM that explains its score, and notifies on good matches. It is a junior AI Engineer portfolio centerpiece, so LangGraph, semantic matching, multi-provider LLM support, and engineering practice (TDD, CI, contributor docs) matter as much as the feature.

## Decisions already made (do not reopen without the user)

- Package `jobscout`, src-layout at repo root (`src/jobscout/`), `uv` + `ruff` + `pytest`, Python 3.12, MIT.
- Single fixed user for now, but **everything is keyed by `user_id`**; `api/deps.py::get_current_user()` is the only place that changes when auth arrives.
- **Operator config (env, `Settings`) is strictly separate from user preferences (DB).** Never put LLM keys, DB URLs, or intervals in user tables; never put job-search preferences in env.
- SQLModel; SQLite by default, Postgres via `DATABASE_URL`. Embeddings stored as bytes — no vector DB.
- LLM and embeddings via LangChain abstractions, provider chosen by env (`LLM_PROVIDER`, `LLM_MODEL`, `EMBEDDING_MODEL`). No direct vendor SDK calls.
- **LangGraph is used only for the per-job matching graph** (`matching/graph.py`): embed → prefilter by cosine similarity → LLM structured evaluation → decide. The prefilter's conditional edge must skip the LLM for low-similarity jobs. Collection, dedup, and notification are plain Python in `pipeline/`.
- APScheduler inside the FastAPI lifespan (no Celery/Redis).
- Interface until stage 6 is FastAPI + Typer CLI only. Stage 6 frontend is Reflex.
- Notification channel is undecided (stage 4); code against the `Notifier` protocol, never a concrete channel.
- Distribution is hybrid: built for self-hosting, with a hosted demo (quotas + BYOK) in stage 7.
- English for code, comments, README; READMEs also in pt-BR and es later.

## Architecture rules

Dependencies point only downward: `sources` (HTTP → `RawJob`, no DB) · `matching` (no HTTP, no sources) · `pipeline` (the only composer: ingest/upsert, filters, backfill, run) · `api` and `cli` are thin shells over `pipeline`. Adding a job board must be one file in `sources/` plus one fixture-based test; the generic contract test in `tests/` runs against every registered source.

Ingest is an **upsert** keyed by `(source, external_id)`: it maintains `first_seen_at`/`last_seen_at`/`is_active`/`content_hash` on `Job`, and a changed hash clears the embedding and marks existing matches `stale`. Running ingest twice with the same data must be a no-op besides `last_seen_at`.

## Roadmap (stage-gated; each stage runs end to end)

0 Foundation → 1 Vertical slice without AI (Arbeitnow, SQLite, CLI, API) → 2 LangGraph matching + backfill → 3 Scheduler + inactive marking → 4 `Notifier` + first channel → 5 More sources → 6 Reflex UI, auth, Postgres/Docker, i18n → 7 Quotas, BYOK, public demo.

Follow this order unless the user says otherwise. TDD for all logic; tests never touch the network (fixtures + `respx`; LangChain fake models). Real-API tests live behind `pytest -m integration` and are off by default.

## Commands

- `uv sync --all-groups` — install (Python 3.12 is pinned in `.python-version`; never use the system Python).
- `uv run pytest` — unit tests, no network. Single test: `uv run pytest tests/sources/test_arbeitnow.py::test_fetch_maps_fields -v`.
- `uv run pytest -m integration` — opt-in tests against real APIs (off by default via `addopts`).
- `uv run ruff check .` / `uv run ruff format .` — lint/format; both must be clean before committing.
- `uv run mypy src` — strict type check of `src/`; must be clean before committing (CI enforces it).
- `uv run jobscout fetch|jobs|serve` — CLI. `serve` runs uvicorn on `jobscout.api.app:app`.
- CI (`.github/workflows/ci.yml`) runs ruff check, ruff format --check, mypy and pytest.

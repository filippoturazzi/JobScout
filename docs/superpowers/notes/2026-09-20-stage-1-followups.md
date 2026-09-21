# Stage 0–1 follow-ups (input for stage 2 planning)

Collected from the whole-branch review of `stage-0-1` (2026-09-20). Nothing here blocks stage 1; each item names the stage that should absorb it.

## Spec clarifications to make before stage 2

1. **§5 step 1 — `Source.fetch(query)` semantics.** Ingest is instance-global. `SearchQuery` only parameterizes APIs that require server-side search (Adzuna, Jooble); sources never drop fetched results; user filtering happens in `pipeline/filters.py` and later in the matching graph. Consequence: `run_ingest` should stop taking `user_id` (or ingest once per distinct query) before the stage 3 scheduler and stage 6 multi-user make the per-user shape load-bearing.
2. **§5/§7 — scope of `content_hash`.** Hash = title + description means `salary_*`, `remote`, `location`, `tags` changes with unchanged text are never persisted. Recommend: refresh all metadata fields on every sighting; use the hash only to invalidate embeddings / mark `Match` rows stale.

## Stage 2 (matching) must include

- **Engine seam (deferred Important).** CLI builds an engine per call; API uses cached `db.get_engine()`; the lifespan (init_db + default-user bootstrap) has no test. Give `get_engine` a settings parameter or a `reset_engine()`, make the CLI use it, add one `with TestClient(app):` lifespan test. Do this as stage 2 task 1.
- **Hook points.** Mark matches stale in the `changed` branch of `upsert_jobs` as one bulk `UPDATE ... WHERE job_id IN (...)`; have `UpsertStats` carry `created_ids` / `changed_ids` (after `session.flush()`) so "only new jobs are matched" is not a racy timestamp query. Wire "preferences changed → backfill" in a new `pipeline/run.py::save_preferences(...)` (not inside `pipeline/users.py`, which must stay a leaf). `update_preferences` should return the changed field names and clear `profile_embedding` when `profile_summary` changes.
- **Filters rewrite (prefilter).** Exclusions and regions are lowercase substring matches: `regions=["US"]` accepts "Sydney, Australia"; `excluded_keywords=["ai"]` rejects "Maintenance Engineer". Use word-boundary matching for keywords and comma-split location segments for regions; share one tokenizer with the title check. Keep the existing `test_filters.py` as regression.
- **`html_to_text` word joins.** Parts are joined with `" "`, so `Java<b>Script</b>` → "Java Script"; hash is stable but embeddings will see mangled tokens. Join with `""` and add whitespace only around block-level tags.
- **`list_jobs` scan.** Loads all active rows before Python filtering + slice; replace with `Match`-driven queries.
- **Decide Match visibility vs. `Job.is_active`** (join-time filter vs. marking stale) before stage 3 deactivation lands.
- Turn on `mypy` now rather than in stage 6.
- Single source of truth for "non-nullable preference fields": the Pydantic validator in `api/schemas.py` hardcodes the list that `pipeline/users.py` derives from column metadata; derive both from one place.

## Stage 3 (scheduler)

- Consider `typer.Typer(pretty_exceptions_enable=False)` for unattended runs on Windows consoles.

## Stage 5 (sources) — source author guide must say

- Never filter fetched results by `query`.
- Use `pydantic.HttpUrl` (or assert `https://`) for `RawJob.url`.
- `html.unescape` every text field.
- Redact query strings from error messages: `IngestResult.error` echoes `str(exc)`, and `httpx.HTTPStatusError` includes the full URL — Adzuna passes `app_id`/`app_key` as query params.
- Dedupe repeated names in `SOURCES` (`dict.fromkeys` in `Settings.source_names`).

## Stage 6 (product)

- Rename table `user` → `users` before any Alembic history exists (Postgres reserved word).
- `sqlalchemy.JSON` maps to `json` on Postgres, not `jsonb`.
- `init_db` on every CLI call becomes Alembic's job.
- `get_current_user` runs `get_or_create_default_user` per request; replace with a pure lookup once auth exists.
- `PUT /preferences` has PATCH semantics; rename or document. Upper-case `salary_currency`.
- Drop redundant single-column indexes on `Job.source` / `Job.external_id` (covered by the unique constraint).

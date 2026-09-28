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

## Added after stage 2a (2026-09-21 whole-branch review)

Stage 2a resolved: engine seam + lifespan test; global ingest; metadata refresh + `created_ids`/`changed_ids`; Unicode token filters; block-aware `html_to_text`; mypy; non-nullable fields derived from the table.

Still open for stage 2b:
- **Hook points confirmed clean.** Stale-marking: inside `upsert_jobs` right after `session.flush()`, bulk `UPDATE match SET status='stale' WHERE job_id IN (chunk)` over `stats.changed_ids`, chunked by `_LOOKUP_CHUNK`, same transaction. `IngestResult` ids are **per source** — `run_pipeline` must concatenate them across results before matching.
- **Backfill on preference save:** `pipeline/run.py::save_preferences(session, settings, user_id, changes)` → `update_preferences` → `backfill_matches`; repoint `PUT /preferences` to it. Clear `profile_embedding` when `"profile_summary" in changes` (additive inside `update_preferences`).
- **`cast(int, user.id)` ×4** (cli.py, api/routers/jobs.py, api/routers/preferences.py ×2): consolidate into a `get_current_user_id()` dependency in `api/deps.py` (keeps "auth changes one function") + a one-liner in `cli.py`, when 2b adds the `/matches` router and CLI `match`.
- **Hash churn warning:** any change to `html_to_text` or `tokenize` after 2b re-embeds every job and stales every match. Batch renderer changes; put this in the stage-5 source-author guide.
- `list_jobs` full scan and `Match` visibility vs `Job.is_active`: decide in 2b's plan.
- Config for 2b: `LLM_PROVIDER`, `LLM_MODEL`, `EMBEDDING_MODEL` (+ provider keys) → `.env.example` and CLAUDE.md operator-config bullet.
- Stage 3: add a `threading.Lock` around `db._engines` when the scheduler thread becomes a second caller.

## Added after stage 2b (2026-09-26 whole-branch review)

Stage 2b resolved: the matching graph, backfill, `/matches`, and the fix wave below it
(provider errors no longer escape `PUT /preferences` or `jobscout match`; `status=low` is
reachable; embeddings commit per chunk; the preference-save backfill is capped at 5
evaluations). Everything here was ruled out of that wave and deferred.

### Stage 3 (scheduler + inactive marking)

- **Move the backfill off the request onto the scheduler.** `PUT /preferences` runs
  `backfill_matches` inline; the current mitigation is the `_BACKFILL_EVALUATION_CAP = 5`
  constant in `pipeline/run.py`. Queueing the work kills the latency problem at the root and
  the cap can go.
- **One matching job on the scheduler**, with jitter and a "did the last run 429" backoff;
  the interval is an operator setting (env), never a user preference.
- **Revisit `SIMILARITY_THRESHOLD` with accumulated data.** Observed 0.503-0.695 over 30
  jobs, with irrelevant postings at 0.62, so the shipped 0.45 is currently inert. Consider
  logging the per-run similarity distribution and a percentile-relative floor instead of an
  absolute one.
- **`save_preferences` stales more than it backfills.** It marks *all* of a user's matches
  stale but backfills only `BACKFILL_WINDOW_DAYS`, so rows outside the window sit `stale`
  until someone runs `jobscout match`. Either scope the staling to the window or let the
  scheduler drain the tail.
- **Add an index on `match(user_id, status)`** — `select_candidates` and `list_matches` both
  filter on that pair.

### Stage 4 (notifier)

- **Decide what re-evaluation does to user state.** Today a staled `notified` or `saved`
  match is rewritten to `new`, so stage 4 will re-notify and stage 6 will lose "saved".
  Either preserve user-set status across re-evaluation or add a `notified_at` column.

### Stage 5 (more sources)

- `select_candidates` loads every active job plus all of the user's matches. Fine at 808
  jobs; revisit when several sources are enabled.

### Stage 6 (UI, auth, Postgres)

- `MatchRun.error` is invisible to the API caller — `PUT /preferences` returns the
  preferences and silently drops the backfill outcome.
- Multi-line LLM reasoning breaks the `jobscout matches` indentation.

### Stage 7 (quotas, BYOK, demo)

- `temperature=0` is unvalidated for OpenAI's o-series models, which reject it.
- Provider keys are typed `str | None` rather than `SecretStr`, so they can end up in a
  repr or a log line.

## Added after the stage-2b fix wave (2026-09-26 scoped re-review)

- **Stage 3 — the preference-save backfill now covers 5 matches, not 25, while still
  staling *all* of them.** `save_preferences` marks every non-dismissed match `stale` but
  re-scores only `_BACKFILL_EVALUATION_CAP`. Staling does not clear `score`, and the
  default `/matches` listing is status-agnostic, so rows 6..N keep serving scores computed
  against the *old* preferences until something re-runs matching. The interactive cap is
  the right call for a request; the scheduler draining the tail is the fix.
- **Stage 3 — `PUT /preferences` still embeds inline.** The cap bounds the LLM half only;
  the same request embeds up to `MAX_EMBEDDINGS_PER_RUN` jobs. That is one batched call and
  the vectors are cached rather than spent, so it is not the dominant latency term, but it
  does consume the whole per-run embedding budget inside an HTTP request.
- **Stage 3/6 — the default `/matches` listing is status-agnostic**, so a `dismissed` row
  with a score is still returned. Pre-dates stage 2b and was not flagged by the whole-branch
  review, but stage 4 would notify on it and stage 6 would show it. Decide the visibility
  rule (`dismissed` hidden, `stale` shown-but-marked?) when the UI lands.
- **Stage 3 — a mid-chunk embedding failure loses the *report* of what was paid for.**
  `_ensure_job_embeddings` now commits per chunk, so the vectors survive, but the exception
  propagates before `embedded_count` is returned: the caller sees `embedded=0`. The money is
  saved; the operator is not told which vectors they bought.
- **Stage 6 — `SIMILARITY_THRESHOLD` and `NULLS LAST` portability.** `ORDER BY ... NULLS
  LAST` is emitted literally; SQLite has supported it since 3.30 (2019), but a self-hosted
  install linking an older `libsqlite3` would get a syntax error on every `/matches` call.
  Worth a startup check when Postgres/Docker land.
- **Stage 5 — `select_candidates` hardcodes `"stale"` as the never-evaluated sentinel**
  (`existing.get(job.id, "stale") in REEVALUATABLE_STATUSES`). If a later stage renames or
  drops `"stale"` from that set, brand-new jobs silently stop being candidates.

## Added after the stage-2b live verification (2026-09-27)

The deferred live run finally happened. Beyond the three defects fixed in `5e17c43`, it
produced the first real calibration data, and it is worse than the earlier note implied.

- **The cosine prefilter is not separating relevant from irrelevant on this corpus.** The
  three highest-similarity jobs (0.652, 0.642, 0.640) were scored **10, 10 and 0** by the
  LLM. A "Software Engineer - PLC/OT" industrial-automation posting scored cosine 0.652
  against a profile reading "Junior AI engineer. Python, FastAPI, LLM applications,
  LangGraph." Everything observed lands in 0.52-0.65 regardless of relevance, so
  `SIMILARITY_THRESHOLD` is not merely inert at 0.45 — there is no threshold that would
  work, because there is no gap to put one in.
- **Hypothesis for stage 4, not yet tested:** `job_text` is probably dominated by
  boilerplate — company blurb, benefits, German legal text — rather than role content, so
  the vectors describe "a German job posting" more than "this job". Worth testing whether
  embedding title + a truncated description beats embedding the whole rendered text.
- **Confounder to control for:** Arbeitnow is a German board and most of the corpus is
  non-tech and non-English, while the profile is English. Stage 5's extra sources may
  change the picture on their own. Also, `titles` is empty on the default user, so the
  deterministic filter passes all 808 jobs and the cosine ranking is doing work it was
  never meant to do alone.
- **A ranking over an unembedded corpus is not a ranking.** With 15 of 808 jobs embedded,
  `match --dry-run` prints "Would evaluate 15 of 808 candidates" over an arbitrary subset,
  not the best 15. Until the backlog is drained the ordering is close to meaningless, and
  the wording oversells it. Stage 3's scheduler drains the backlog; the CLI wording should
  say how many candidates still lack a vector.
- **Per-job error isolation is proven in the wild.** One evaluation died with
  `RemoteProtocolError: Server disconnected`; it was logged and counted, the other two
  committed, and the run exited 0. That path had only ever been exercised by a test double.

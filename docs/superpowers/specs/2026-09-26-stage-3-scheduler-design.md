# Stage 3 — Scheduler and inactive marking: Design Spec

**Date:** 2026-09-26
**Status:** Approved for planning
**Parent spec:** `docs/superpowers/specs/2026-09-19-jobscout-design.md` (amends §4, §5 step 5, §8)
**Input:** the stage-3 items in `docs/superpowers/notes/2026-09-20-stage-1-followups.md`

## 1. Purpose

Make JobScout run by itself. Today every job in the database arrived because someone typed
`jobscout fetch`, and every score exists because someone typed `jobscout match`. This stage
puts both on a schedule inside the API process, expires postings nobody has seen in a while,
and gives the operator a way to prove it is working.

Parent-spec success criterion: *left running for an hour, new jobs appear on their own.*

## 2. Decisions

| Topic | Decision | Rationale |
|---|---|---|
| Job topology | Two jobs on independent intervals: `ingest_job` (global, default 60 min) and `match_job` (all users, default 15 min). | Ingest is cheap HTTP; matching spends LLM and embedding quota. One interval for both means either fetching rarely or burning quota often. Independent jobs also fail independently. |
| Preference save | `PUT /preferences` stales and returns; it then asks the scheduler for one immediate out-of-band `match_job` run. `_BACKFILL_EVALUATION_CAP` and the inline backfill are removed. | Kills the request-latency problem at the root while keeping the result nearly immediate. Also closes the "stales everything, re-scores five" asymmetry: the scheduler drains the tail. |
| Observability | A `Run` table, one row per job execution, plus `GET /runs`. The backoff reads it. | The success criterion has to be checkable, and the history must survive a restart. In-memory state would lose both. |
| Deactivation scope | Per source, and only for sources whose ingest succeeded in that execution. | "I did not ask" is not "it no longer exists". A source that is down, erroring, or removed from `SOURCES` must not have its catalogue expire behind the operator's back. |
| Backoff trigger | Consecutive failed `Run` rows for that job, not a 429 specifically. Skip `2**k` ticks, capped by `MAX_BACKOFF_TICKS`. | Detecting 429 means substring-matching a provider message, which breaks when the wording changes and misses the other reasons to stop hammering: network, auth, daily quota. Repeated failure is the signal; the message is kept for diagnosis only. |
| Scheduler lifetime | Inside the FastAPI lifespan, started on startup and shut down on exit, behind `SCHEDULER_ENABLED`. The CLI stays manual. | One process, no Celery/Redis (parent spec §22). Without the flag every test that builds the app would start threads. |
| Jobstore | None. Jobs are registered from `Settings` at every startup. | A persistent jobstore would let a schedule from an old configuration outlive the configuration that created it. |

## 3. Amendments to the parent spec

- **§4 config:** add `SCHEDULER_ENABLED`, `INGEST_INTERVAL_MINUTES`, `MATCH_INTERVAL_MINUTES`,
  `SCHEDULER_JITTER_SECONDS`, `RUN_RETENTION_DAYS`, `MAX_BACKOFF_TICKS`. The single
  `SCHEDULER_INTERVAL_MINUTES` named there is replaced by the two per-job intervals.
- **§5 step 5:** "jobs whose `last_seen_at` is older than `INACTIVE_AFTER_DAYS` are marked
  `is_active = False`, **restricted to the sources that were fetched successfully in that
  execution**."
- **§8:** the scheduler is covered by tests that never sleep — see §7.

## 4. Components

```
src/jobscout/scheduler.py            JobScoutScheduler; ingest_job(); match_job();
                                     should_skip_for_backoff(); wake_matching()
src/jobscout/models/run.py           Run table
src/jobscout/pipeline/liveness.py    deactivate_stale_jobs(session, settings, source)
src/jobscout/pipeline/run.py         save_preferences loses the inline backfill
src/jobscout/api/routers/runs.py     GET /runs
src/jobscout/api/app.py              lifespan starts/stops the scheduler; app.state.scheduler
src/jobscout/db.py                   threading.Lock around _engines
src/jobscout/cli.py                  pretty_exceptions_enable=False
src/jobscout/models/match.py         index on (user_id, status)
pyproject.toml                       apscheduler dependency
```

`scheduler.py` is a thin composer over `pipeline/`, in the same layer as `api` and `cli`: it
orchestrates and records, it holds no matching or ingest logic. `pipeline/liveness.py` is new
rather than part of `ingest.py`, which brings data in; expiring data is a separate concern.

## 5. Behavior details

### 5.1 `Run`

`id`, `job: str` (`"ingest"` or `"match"`), `started_at`, `finished_at: datetime | None`,
`ok: bool`, `error: str | None`, and counters as a JSON column: `created`, `updated`,
`changed`, `deactivated` for ingest; `candidates`, `evaluated`, `skipped_low`, `embedded`,
`embeddings_pending`, `errors` for match. A JSON column rather than a wide table because the
two jobs report different things and stage 4 will add a third.

The counters live in one JSON column named `counters`. Rows older than `RUN_RETENTION_DAYS`
are pruned in the transaction that *creates* a row (§5.2 step 1), not the one that finishes it,
so pruning happens once per execution.

### 5.2 `ingest_job`

1. Open a session. Write the `Run` row with `ok=False` up front, so a hard crash still leaves a trace.
2. For each configured source: `ingest()`. Accumulate the per-source `IngestResult`.
3. For each source whose result carries no error: `deactivate_stale_jobs(session, settings, source)` —
   `UPDATE job SET is_active = False WHERE source = :source AND is_active AND last_seen_at < now - INACTIVE_AFTER_DAYS`.
4. Finish the `Run` row: counters, `ok`, `finished_at`. Any exception is caught and recorded.

### 5.3 `match_job`

1. If `should_skip_for_backoff(...)` says so, return without writing a `Run` row.
2. For each user: `run_match(session, settings, user_id)` with the existing per-run caps.
3. Record one `Run` row with the summed counters. Exceptions are caught and recorded.

### 5.4 `should_skip_for_backoff`

```python
def should_skip_for_backoff(session: Session, job: str, tick: int, settings: Settings) -> bool
```

A pure function of its arguments, so it can be tested without a scheduler. `session` supplies
the durable half — the number of consecutive `ok=False` rows for that job, counted most recent
first, reset by the first `ok=True`. `tick` supplies the volatile half: a per-job counter the
scheduler increments on every firing and passes in.

With `k` consecutive failures the job runs only when `tick % min(2**k, 2**MAX_BACKOFF_TICKS) == 0`,
so `k=0` never skips. The tick counter is deliberately not persisted: losing it on restart costs
one extra attempt, which is the safe direction to be wrong in.

A skipped tick writes no `Run` row, so skipping cannot itself deepen the backoff.

### 5.5 `wake_matching`

`JobScoutScheduler.wake_matching()` adds a one-off `match_job` with `next_run_time=now`, id
`match-wake`, and `replace_existing=True` so repeated saves collapse into one pending run.
`save_preferences` calls it through an optional callable; when the API runs without a
scheduler, or the CLI calls `save_preferences`, it is a no-op. The API must not fail because
no scheduler exists.

### 5.6 Concurrency

Both jobs use `max_instances=1`, `coalesce=True`, and `jitter=SCHEDULER_JITTER_SECONDS`. Each
execution opens and closes its own `Session`; no session crosses a thread boundary.
`db.get_engine` takes a `threading.Lock` around the `_engines` dict — a race there creates two
engines, which wastes a pool for file SQLite and produces **two different databases** under
the `StaticPool` in-memory configuration the tests use.

## 6. Out of scope

Celery/Redis; a persistent APScheduler jobstore; per-user intervals; notifications (stage 4);
a UI for `/runs` (stage 6); changing `SIMILARITY_THRESHOLD`.

`SIMILARITY_THRESHOLD` stays at 0.45 and stays inert. Calibrating it needs a sample this stage
has not accumulated yet: the observed range was 0.503-0.695 over 30 jobs, with irrelevant
postings scoring 0.62. `match_job` logs the per-run similarity distribution so stage 4 can
decide from real data, and a percentile-relative floor stays on the table.

## 7. Testing

No test sleeps, waits for a tick, or lets real time pass.

- **Job logic** (`ingest_job`, `match_job`, `deactivate_stale_jobs`) is tested by calling the
  functions directly against in-memory SQLite. No scheduler is involved.
- **Deactivation:** a source that errored keeps its stale jobs; a source that succeeded loses
  them; a job seen inside the window survives either way; an already-inactive job is not
  counted twice.
- **Wiring** is tested through `scheduler.get_jobs()`: enabled registers two jobs at the
  configured intervals; `SCHEDULER_ENABLED=false` registers none; `wake_matching()` adds the
  one-off and a second call replaces rather than duplicates it; calling it with no scheduler
  does not raise.
- **Backoff** is a pure function of the `Run` table: seed failed rows, assert the skip decision.
- **`Run`:** counters persisted; a raising job still leaves `ok=False` with the message;
  pruning drops rows past the retention window and keeps the rest.
- **`save_preferences`** no longer evaluates anything and no longer needs a provider.
- **`GET /runs`** returns newest first, honours `limit`, and filters by `job`.

## 8. Done when

`uv run pytest` green with no warnings; `mypy src` clean; ruff clean; CI green;
`uv run jobscout serve` left running ingests on its own schedule and `GET /runs` shows the
executions; a preference save returns immediately and is followed by a woken match run.

## 9. Carried forward, deliberately not solved here

Once matching runs unattended every 15 minutes, it re-scores matches the user already marked
`saved` or `notified`, because staling rewrites the status to `new`. That is harmless today —
nobody is notified and there is no UI — but it becomes re-notification in stage 4 and a lost
"I saved this" in stage 6. The scheduler makes it more likely, not less. It belongs to stage 4,
where the `Notifier` makes the right answer visible; it is already recorded in the follow-up
notes.

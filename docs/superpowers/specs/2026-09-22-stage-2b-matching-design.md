# Stage 2b — LangGraph matching: Design Spec

**Date:** 2026-09-22
**Status:** Approved for planning
**Parent spec:** `docs/superpowers/specs/2026-09-19-jobscout-design.md` (§6 graph, §7 `Match`) — this document refines both
**Inputs:** `docs/superpowers/specs/2026-09-21-stage-2a-groundwork-design.md`; `docs/superpowers/notes/2026-09-20-stage-1-followups.md` (§ "Added after stage 2a")
**Baseline:** `main` @ `19a61fa` (stages 0, 1, 2a merged; 96 tests, mypy strict clean)

## 1. Purpose

Turn the collected jobs into explained matches. For each (job, user) pair worth the cost, produce a 0–100 fit score with a written justification, matched/missing skills and red flags, using embeddings to decide what is worth an LLM call. This is the stage that makes JobScout an AI product rather than a job scraper, so the graph must be load-bearing and the cost must be bounded.

## 2. Decisions

| Topic | Decision | Rationale |
|---|---|---|
| Gate into the graph | Only jobs that pass the deterministic filter (`pipeline/filters.py::job_matches_preferences`) are embedded and evaluated | Work mode, region, hard exclusions and titles are free to check; the LLM should only see plausible candidates. Backfill re-runs when preferences are relaxed. |
| Prefilter rejection | Writes a `Match` with `similarity`, `score = None`, `status = "low"` | Spec §7. The row is the memory that stops re-evaluating the same pair every run, and it explains "why didn't this job show up". |
| Preference change | Matching-relevant changes mark existing matches `stale`; the next run re-evaluates them within the per-run cap | Keeps scores consistent with the current profile without a burst of LLM calls on `PUT /preferences`. |
| Vector storage | stdlib `array("f").tobytes()` in the existing `bytes` columns; cosine in pure Python | No new dependency; ~500 jobs × 768 dims is tens of milliseconds. Dimension is stored so a model change is detectable. |
| Top-K vs. graph | Selection happens in `pipeline/matching.py` (batch embed → cosine → sort → top-K under the cap); the graph runs per selected job and keeps all four nodes | Best candidates first and one batched embedding call, while the conditional edge stays real (cache-miss and below-threshold paths are exercised). |
| Missing provider/key | `fetch`, `jobs` and the job endpoints work with no key; only `match` / `GET /matches` fail, with a message naming the variables to set and exit code 2 | Keeps stage 1's "clone and see real jobs in 30s"; tests need no key. |
| LLM output | `with_structured_output(EvaluationResult)`: `score`, `reasoning`, `matched_skills`, `missing_skills`, `red_flags` | Feeds the stage-6 dashboard and the stage-4 notification; already anticipated by §7. |
| Match visibility vs. `Job.is_active` | Join-time filter: `GET /matches` and the CLI listing return only matches whose job is active | Resolves the item deferred from stage 2a. Deactivating a job never writes to `match`; if the job comes back, so does its match. |
| Providers | `LLM_PROVIDER` selects a builder with a lazy import: `google` (installed), `openai`, `ollama` (clear "pip install …" error if absent) | The multi-provider story without shipping three SDKs. |
| Scope | One plan, one branch | The halves are not independently useful: a graph with no CLI is not demoable; backfill with no graph does nothing. |

Versions verified on 2026-09-22: `langgraph` 1.2.12, `langchain-google-genai` 4.4.0 (pulls `langchain-core` ≥1.6.1), `langchain-core` 1.6.4. Current Gemini names in that package's docs: chat `gemini-3.5-flash`, embeddings `gemini-embedding-*`. **Confirmed against the real API in the integration task (Task 13): `gemini-3.5-flash` exists as documented; the placeholder `gemini-embedding-001` does not exist and the API answered it with a misleading `429 RESOURCE_EXHAUSTED` rather than a 404 — the working embedding model is `gemini-embedding-2`, which honours `outputDimensionality: 768`. The table below reflects the corrected default.**

## 3. Components

```
src/jobscout/matching/           no HTTP, no sources, no api/cli imports
  __init__.py
  llm.py        chat_model(settings) -> BaseChatModel ; embeddings(settings) -> Embeddings
                lazy per-provider builders; MissingProviderError with the variables to set
  vectors.py    pack(vec) -> bytes ; unpack(blob) -> list[float] ; cosine(a, b) -> float
  schemas.py    EvaluationResult (LLM output) ; MatchState (graph state)
  prompts.py    SYSTEM_PROMPT ; build_user_prompt(prefs, job, locale) -> str
  graph.py      build_graph(deps) -> CompiledGraph ; nodes embed_job/prefilter/record_low/evaluate/decide

src/jobscout/models/match.py     Match table (+ re-export from models/__init__.py)

src/jobscout/pipeline/
  matching.py   select_candidates(...) ; run_match(session, settings, user_id, limit=None, dry_run=False) -> MatchRun
  backfill.py   backfill_matches(session, settings, user_id, window_days) -> MatchRun
  ingest.py     + stale-marking for changed_ids after flush
  users.py      update_preferences returns changed field names; clears profile_embedding when profile_summary changes
  run.py        + save_preferences(session, settings, user_id, changes)

src/jobscout/api/
  deps.py       + get_current_user_id() -> int   (removes the four cast(int, user.id))
  schemas.py    + MatchRead (nested JobRead), MatchStatus
  routers/matches.py   GET /matches
  routers/preferences.py  PUT now calls save_preferences

src/jobscout/cli.py   + match, matches commands
```

Dependency rules hold: `matching` imports `models` and `config` only (never `sources`, `api`, `cli`, or `pipeline`); `pipeline` composes `matching` + `models`; `api`/`cli` stay thin.

## 4. Data model

**`Match`** — unique on `(job_id, user_id)`; `id`, `created_at`, `updated_at` as elsewhere.

| Field | Type | Notes |
|---|---|---|
| `job_id` | `int` FK `job.id`, indexed | |
| `user_id` | `int` FK `user.id`, indexed | |
| `similarity` | `float` | cosine of job vs. profile embedding |
| `score` | `int \| None` | 0–100; `None` when the prefilter rejected |
| `reasoning` | `str \| None` | |
| `matched_skills`, `missing_skills`, `red_flags` | `list[str]` JSON, non-null, default `[]` | |
| `status` | `str` | `new` \| `seen` \| `saved` \| `dismissed` \| `notified` \| `low` \| `stale` |
| `llm_model` | `str \| None` | which model produced the score |

**Status lifecycle.** A fresh evaluation writes `new` (or `low` when the prefilter rejected). The user moves it to `seen`/`saved`/`dismissed` (stage 6 UI; stage 2b only reads these). Stage 4 sets `notified`.

Re-evaluation: a pair becomes `stale` when the job's `content_hash` changed (ingest, via `changed_ids`) or the user changed a matching-relevant preference (`titles`, `seniority`, `required_skills`, `nice_to_have_skills`, `min_salary`, `profile_summary`). **Only `stale` rows are candidates again.** `low` is terminal until something stales it — that is precisely what makes the row worth writing: without it every run would re-score the same rejected pairs. **`dismissed` is never re-evaluated and is never marked stale** — the user's rejection stands.

## 5. Behavior

### 5.1 `run_match(session, settings, user_id, limit=None, dry_run=False) -> MatchRun`

1. Load preferences. If `profile_summary` is empty → return a `MatchRun` with `error="no profile summary"` (nothing to match against) and evaluate nothing.
2. Candidate query: active jobs that pass `job_matches_preferences` and either have no `Match` for this user or have one with `status == "stale"`. Every other status (`new`, `seen`, `saved`, `notified`, `low`, `dismissed`) is skipped.
3. Ensure the profile embedding: if `profile_embedding` is `None` or its dimension differs from `EMBEDDING_DIM`, embed `profile_text` and store it.
4. Batch-embed candidates whose `Job.embedding` is missing or of the wrong dimension — bounded by `MAX_EMBEDDINGS_PER_RUN` — one `embed_documents` call, chunked at 100 texts. Candidates lacking a vector are reconsidered in later runs.
5. Compute cosine for every candidate that now has a vector, sort descending, keep the first `min(limit or MAX_LLM_EVALUATIONS_PER_RUN, len(candidates))`.
6. `dry_run` stops here and reports what would be evaluated.
7. For each selected job, run the compiled graph; persist the resulting `Match` (upsert on the unique pair).
8. Return `MatchRun(evaluated, skipped_low, embedded, embeddings_pending, errors)`.

A candidate that never made the top-K keeps no row at all, so it is reconsidered in the next run — only `record_low` (graph actually ran) writes the terminal `low` row.

`profile_text` = `profile_summary` plus the preference lists (titles, seniority, required/nice-to-have skills, regions, work modes), joined into one paragraph. `job_text` = title, company, location, tags and the description truncated to 6000 characters.

### 5.2 Graph

State `MatchState` (TypedDict, total=False): `job_id`, `user_id`, `job_text`, `profile_text`, `job_embedding`, `profile_embedding`, `similarity`, `evaluation`, `llm_model`, `should_notify`.

```
embed_job ─► prefilter ─(similarity < SIMILARITY_THRESHOLD)─► record_low ─► END
                   └────(≥ threshold)───────────────────────► evaluate ─► decide ─► END
```

- `embed_job` — uses the cached vector when present; otherwise embeds and caches. Normal runs arrive pre-embedded from step 4; this node covers cache misses and keeps the graph runnable standalone.
- `prefilter` — cosine; the conditional edge is what bounds cost. A counting fake proves the LLM is not called on the low path.
- `evaluate` — `chat_model.with_structured_output(EvaluationResult).invoke(messages)`; records `llm_model`.
- `decide` — `should_notify = score >= prefs.min_score_to_notify`; stage 4 consumes it.

Errors inside `evaluate` (rate limit, parse failure) do not abort the run: the pair is left unwritten, the error is recorded in `MatchRun.errors`, and the loop continues — same isolation principle as ingest (§8 of the parent spec).

### 5.3 `save_preferences(session, settings, user_id, changes)`

`update_preferences` (returns the changed field names and clears `profile_embedding` when `profile_summary` changed) → if any changed field is matching-relevant, bulk-mark that user's non-`dismissed` matches `stale` → `backfill_matches(..., BACKFILL_WINDOW_DAYS)` bounded by the same per-run cap. `PUT /preferences` calls this; the response still returns the preferences.

### 5.4 Stale-marking on ingest

After `session.flush()` in `upsert_jobs`, for `stats.changed_ids`, one bulk `UPDATE match SET status='stale' WHERE job_id IN (chunk) AND status != 'dismissed'`, chunked by `_LOOKUP_CHUNK`, in the same transaction.

### 5.5 Configuration (operator, env)

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `google` | `google` \| `openai` \| `ollama` |
| `LLM_MODEL` | `gemini-3.5-flash` | chat model for evaluation |
| `EMBEDDING_MODEL` | `gemini-embedding-2` | embedding model |
| `EMBEDDING_DIM` | `768` | requested `output_dimensionality`; a stored vector of another length is re-embedded |
| `SIMILARITY_THRESHOLD` | `0.45` | floor below which the LLM is skipped |
| `MAX_EMBEDDINGS_PER_RUN` | `200` | hard cap on embedding work per run; remaining candidates are reconsidered in later runs |
| `MAX_LLM_EVALUATIONS_PER_RUN` | `25` | hard cap per run and per backfill |

Provider keys (`GOOGLE_API_KEY`, `OPENAI_API_KEY`) are read by the provider packages from the environment; they are documented in `.env.example` and never stored in user tables. The threshold started deliberately low — top-K does the real selection; the integration task (Task 13) prints the observed similarity distribution so it can be calibrated from data. Calibrated 2026-09-25: over 30 active jobs against a "Junior AI engineer... Python, FastAPI, LLM applications, LangGraph. Remote, Europe." profile, cosine similarity ranged 0.503-0.695 — the original 0.35 floor never fired. No clean gap between plainly-relevant and plainly-irrelevant titles was visible at that sample size, so the threshold was raised conservatively to `0.45`, inside the gap between the old floor and the observed minimum.

## 6. Interfaces

**CLI**
- `jobscout match [--limit N] [--dry-run]` — prints `evaluated=X skipped_low=Y errors=Z` (dry run: the titles that would be evaluated with their similarity).
- `jobscout matches [--min-score N] [--limit N]` — score, title, company, one-line reasoning, URL; active jobs only, score desc.

**API**
- `GET /matches?min_score=&status=&limit=` → `list[MatchRead]` (`score`, `similarity`, `reasoning`, skill lists, `status`, nested `JobRead`), active jobs only, `score` desc with `NULL`s last.
- `PUT /preferences` — unchanged contract; now routed through `save_preferences`.
- `deps.get_current_user_id() -> int` replaces the four `cast(int, user.id)` sites.

## 7. Testing

No network in unit tests. Embeddings: `langchain_core.embeddings.DeterministicFakeEmbedding`. Chat: a local double in `tests/matching/fakes.py` implementing `with_structured_output(schema).invoke(...)` and counting calls (the langchain fake chat models do not implement structured output usefully).

Required cases: `pack`/`unpack` round-trip and `cosine` against hand-computed values; below-threshold path writes `low` and makes **zero** LLM calls (counter asserts 0); top-K picks the highest similarities and stops at the cap; `stale` is re-evaluated, `dismissed` is not; a failing `evaluate` leaves other pairs intact and lands in `MatchRun.errors`; `save_preferences` clears the profile embedding, marks stale and backfills; ingest marks matches stale for `changed_ids`; `GET /matches` hides matches whose job is inactive; missing provider key produces the named error, not a traceback.

Integration (`-m integration`, off by default, needs a real key): one real evaluation end to end, printing the similarity distribution over the jobs currently in the DB and confirming the model names in §5.5.

## 8. Out of scope

Notifications (stage 4), scheduler (stage 3), UI (stage 6), quotas/BYOK (stage 7). `list_jobs` keeps its current shape — score-ordered browsing is `/matches`. No vector database: cosine in Python over cached bytes is the stage-2b answer.

## 9. Done when

`uv run pytest` green with no warnings; `uv run mypy src` clean; CI green; `uv run jobscout match` on a real key produces scored, explained matches over real Arbeitnow jobs; `GET /matches` returns them; a second `match` run evaluates nothing new (idempotent); `PUT /preferences` triggers a bounded backfill.

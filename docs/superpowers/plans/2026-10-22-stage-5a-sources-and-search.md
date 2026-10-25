# Stage 5a — Sources and search: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the catalogue-dump corpus with four term-searched job sources, and turn a user's paragraph into the search that drives them.

**Architecture:** `JobSource` already carries a `SearchQuery` that nothing uses — stage 1 anticipated this. Sources gain a declared search capability and a declared credential requirement; the registry drops sources whose credentials are absent instead of failing. A new `matching/terms.py` turns the paragraph into ranked search terms plus structured preferences, guarded by a hash so it costs one LLM call per edit. A new `pipeline/search.py` composes terms → fetch → score into one background run that commits incrementally and resumes across runs.

**Tech Stack:** Python 3.12, `uv`, SQLModel, httpx + `respx` for tests, LangChain abstractions for the LLM, APScheduler. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-22-stage-5-sources-and-dashboard-design.md`

**Scope:** this plan is the backend half, verifiable through the API and CLI. The dashboard, i18n and the design system are a second plan.

## Global Constraints

- **No scraping, ever.** Only documented public APIs. LinkedIn and Gupy are out and must not be re-proposed.
- Tests never touch the network: `respx` with fixtures captured from the live API, never hand-written. No test calls an LLM; use the existing fake models.
- `sources/` performs no DB work and imports nothing from `pipeline/`. `matching/terms.py` has no HTTP and no sources. `pipeline/` is the only composer. `api/` stays a thin shell.
- Operator config (keys, intervals, enabled sources) lives in env/`Settings`. User preferences live in the DB. Never cross them.
- Ingest stays an upsert on `(source, external_id)`; running it twice with the same data is a no-op besides `last_seen_at`.
- Existing caps stand: `max_embeddings_per_run=100`, `max_llm_evaluations_per_run=25`.
- `uv run pytest`, `uv run mypy src`, `uv run ruff check .`, `uv run ruff format --check .` must all be clean before every commit.
- English for code, comments and docs.
- Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` on its own line in the body.

## Review Focus

Five conditions the spec implies that no happy path exercises. Each has a test assigned to the task that owns the code.

1. **A source returns a row missing a field `RawJob` requires** (no description, no url). Expected: that row is skipped and named in the run's errors; the other rows from the same response are still ingested. One malformed posting must not cost a whole fetch. (Task 2)
2. **A keyed source has a key that is present but wrong** (401/403), which is different from absent. Expected: that source fails, is named in the run's errors, and the other sources still produce results — the run is ok if any source succeeded. (Task 4)
3. **A source returns 429 partway through a multi-term fetch.** Expected: the jobs already fetched are kept and ingested, the remaining terms for that source are abandoned, and the run says so. Discarding completed work because a later call failed is the expensive mistake. (Task 6)
4. **The paragraph is empty, or yields no usable terms.** Expected: the run does not start and says why, rather than searching every source for the empty string and ingesting the whole internet. (Task 5)
5. **Two different terms return the same job.** Expected: one row, and the run's `fetched` counter does not count it twice — otherwise the progress bar reports work that does not exist. (Task 6)

---

### Task 1: Source capability and credential-aware registry

**Files:**
- Modify: `src/jobscout/sources/base.py`
- Modify: `src/jobscout/sources/registry.py`
- Modify: `src/jobscout/config.py:19` (the `sources` default)
- Test: `tests/sources/test_registry.py`

**Interfaces:**
- Produces: `JobSource.supports_search: bool` (class attribute); `SourceStatus(name: str, active: bool, reason: str | None)`; `build_sources(settings: Settings) -> list[JobSource]` (unchanged signature, now skipping sources without credentials); `source_statuses(settings: Settings) -> list[SourceStatus]`.

- [ ] **Step 1: Write the failing tests** in `tests/sources/test_registry.py`

```python
def test_a_source_without_its_credentials_is_not_built():
    settings = Settings(sources="himalayas,adzuna", adzuna_app_id=None, adzuna_app_key=None)
    assert [s.name for s in build_sources(settings)] == ["himalayas"]

def test_source_statuses_name_the_missing_credential():
    settings = Settings(sources="himalayas,adzuna", adzuna_app_id=None, adzuna_app_key=None)
    statuses = {s.name: s for s in source_statuses(settings)}
    assert statuses["himalayas"].active is True
    assert statuses["adzuna"].active is False
    assert "ADZUNA_APP_ID" in statuses["adzuna"].reason

def test_an_unknown_source_name_still_raises():
    with pytest.raises(ValueError, match="Unknown source"):
        build_sources(Settings(sources="nope"))

def test_arbeitnow_is_not_enabled_by_default():
    assert "arbeitnow" not in Settings().source_names

def test_the_scheduler_is_off_by_default():
    assert Settings().scheduler_enabled is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/sources/test_registry.py -v`
Expected: FAIL on the missing `source_statuses` import.

- [ ] **Step 3: Implement**

Add `supports_search: bool` to the `JobSource` protocol, defaulting to `False` on `ArbeitnowSource`. Add `SourceStatus` to `sources/base.py`. In `registry.py`, give each entry in `SOURCE_FACTORIES` a companion predicate that reports whether its credentials are present, and name the missing environment variable in the reason. `build_sources` keeps raising on an unknown name — a typo in `SOURCES` is still an error — but silently skips a known source whose credentials are absent.

Change the `sources` default in `config.py:19` to `"himalayas,remotive,adzuna,jooble"`. Arbeitnow stays registered and contract-tested but off by default (spec §2).

Flip `scheduler_enabled` to default `False` (spec §2): a fresh clone must not spend someone's LLM quota on a schedule they never asked for. Existing scheduler tests that assume it is on must now set it explicitly — change the tests, not the default.

- [ ] **Step 4: Run to verify they pass, plus the existing contract test**

Run: `uv run pytest tests/sources/ -v`
Expected: PASS, including the generic contract test against Arbeitnow.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/sources/ src/jobscout/config.py tests/sources/test_registry.py
git commit -m "feat: let sources declare search support and credential needs"
```

---

### Task 2: The Himalayas source

**Files:**
- Create: `src/jobscout/sources/himalayas.py`
- Create: `tests/sources/test_himalayas.py`
- Create: `tests/fixtures/himalayas_search.json` (captured from the live API, not written by hand)
- Modify: `src/jobscout/sources/registry.py`

**Interfaces:**
- Consumes: `JobSource`, `RawJob`, `SearchQuery`, `supports_search` (Task 1).
- Produces: `HimalayasSource(max_pages: int = 1)` with `name = "himalayas"`, `supports_search = True`.

**API facts, verified live on 2026-10-22 — do not take these from third-party docs, which are wrong:**
- Search: `GET https://himalayas.app/jobs/api/search?q=<term>&page=<n>`. **The parameter is `q`.** `query=`, `search=` and `keyword=` are all ignored and return the unfiltered catalogue (127 255 rows) — `q=kubernetes` returns 5 000.
- Search pages are 20 rows; there is no cursor on search, only `?page=`.
- Response shape: `{"totalCount": int, "jobs": [{title, excerpt, companyName, companySlug, employmentType, minSalary, maxSalary, salaryPeriod, currency, seniority: [...], locationRestrictions: [...], ...}]}`.
- `locationRestrictions` is a list of country names; `"Brazil"` appears in it when the job accepts Brazil.

- [ ] **Step 1: Capture the fixture**

```bash
curl -s "https://himalayas.app/jobs/api/search?q=machine%20learning%20engineer&page=1" \
  -H "User-Agent: JobScout/0.1" > tests/fixtures/himalayas_search.json
```

Trim it to three jobs by hand, keeping every field each job carries. Add one job with `"excerpt": ""` and one with no salary fields, so Review Focus 1 and the salary-absent path have real data.

- [ ] **Step 2: Write the failing tests** in `tests/sources/test_himalayas.py`

```python
def test_fetch_maps_fields(respx_mock): ...        # title, company, url, tags from seniority, salary
def test_fetch_sends_q_not_query(respx_mock):      # pins the parameter name the docs get wrong
    ...                                            # assert "q=" in the recorded request URL
def test_remote_restrictions_become_location(respx_mock): ...
def test_a_job_missing_a_required_field_is_skipped_and_the_rest_survive(respx_mock): ...
def test_one_request_per_term(respx_mock): ...     # SearchQuery(keywords=["a","b"]) -> 2 calls
def test_no_keywords_fetches_nothing(respx_mock): ...
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/sources/test_himalayas.py -v`
Expected: FAIL, module not found.

- [ ] **Step 4: Implement `HimalayasSource.fetch(query: SearchQuery) -> list[RawJob]`**

One request per keyword, `max_pages` pages each. `external_id` comes from the job's own id field in the fixture. Build `description` from `excerpt` — Himalayas search does not return a full body. Reuse `sources/text.py` for any HTML. A job that cannot be mapped is skipped, not raised.

- [ ] **Step 5: Register it and run the suite**

Add `"himalayas"` to `SOURCE_FACTORIES` with no credential predicate.
Run: `uv run pytest tests/sources/ -v`
Expected: PASS, including the generic contract test now covering Himalayas.

- [ ] **Step 6: Commit**

```bash
git add src/jobscout/sources/himalayas.py tests/sources/test_himalayas.py tests/fixtures/himalayas_search.json src/jobscout/sources/registry.py
git commit -m "feat: add the Himalayas source, searched by term"
```

---

### Task 3: The Remotive source

**Files:**
- Create: `src/jobscout/sources/remotive.py`
- Create: `tests/sources/test_remotive.py`
- Create: `tests/fixtures/remotive_search.json`
- Modify: `src/jobscout/sources/registry.py`

**Interfaces:**
- Produces: `RemotiveSource()` with `name = "remotive"`, `supports_search = True`.

**API facts, verified live:** `GET https://remotive.com/api/remote-jobs?search=<term>`. Response `{"job-count": int, "jobs": [{id, title, company_name, candidate_required_location, url, description, salary, publication_date, tags, ...}]}`. `description` is HTML.

- [ ] **Step 1: Capture the fixture**

```bash
curl -s "https://remotive.com/api/remote-jobs?search=machine+learning" \
  -H "User-Agent: JobScout/0.1" > tests/fixtures/remotive_search.json
```

Trim to three jobs, keeping one with an empty `salary`.

- [ ] **Step 2: Write the failing tests** in `tests/sources/test_remotive.py`

Same six shapes as Task 2, with `search=` as the parameter this source sends, plus:

```python
def test_html_description_is_rendered_to_text(respx_mock): ...  # uses sources/text.py
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/sources/test_remotive.py -v`

- [ ] **Step 4: Implement `RemotiveSource.fetch`**, register it, run `uv run pytest tests/sources/ -v`

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/sources/remotive.py tests/sources/test_remotive.py tests/fixtures/remotive_search.json src/jobscout/sources/registry.py
git commit -m "feat: add the Remotive source"
```

---

### Task 4: The keyed Brazilian sources — Adzuna and Jooble

**Files:**
- Create: `src/jobscout/sources/adzuna.py`, `src/jobscout/sources/jooble.py`
- Create: `tests/sources/test_adzuna.py`, `tests/sources/test_jooble.py`
- Create: `tests/fixtures/adzuna_search.json`, `tests/fixtures/jooble_search.json`
- Modify: `src/jobscout/config.py`, `src/jobscout/sources/registry.py`, `.env.example`

**Interfaces:**
- Consumes: the credential predicates from Task 1.
- Produces: `AdzunaSource(app_id: str, app_key: str, country: str = "br")` with `name = "adzuna"`; `JoobleSource(api_key: str)` with `name = "jooble"`. Both `supports_search = True`.
- Settings gained: `adzuna_app_id: str | None`, `adzuna_app_key: str | None`, `adzuna_country: str = "br"`, `jooble_api_key: str | None`.

**Unverified — confirm before writing the fixture.** Neither API could be probed without a key. Adzuna: `GET https://api.adzuna.com/v1/api/jobs/{country}/search/1?app_id=&app_key=&what=<term>&results_per_page=`. The `br` country code is consistent across every third-party source but unconfirmed; an unauthenticated request returns the same generic HTML error for a valid and a bogus country, so it proves nothing. Jooble: sources disagree between `GET https://us.jooble.org/api/{key}/` and `POST https://jooble.org/api/{key}` with a JSON body. **Read the official docs after registering, then write the fixture from a real response.** If `br` turns out not to exist, stop and report it — do not substitute another country.

- [ ] **Step 1: Register for both free keys, confirm the endpoints, capture both fixtures**

Put the keys in `.env` (never commit them). Capture one real response per source, trim to three jobs each.

- [ ] **Step 2: Write the failing tests**

Per source, the Task 2 shapes plus:

```python
def test_credentials_are_sent(respx_mock): ...                  # app_id/app_key, or the key in the path
def test_an_invalid_key_raises_and_names_the_source(respx_mock): ...   # 401/403, Review Focus 2
def test_brazilian_location_is_preserved(respx_mock): ...
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/sources/test_adzuna.py tests/sources/test_jooble.py -v`

- [ ] **Step 4: Implement both sources and their settings**

Register each with a credential predicate naming its environment variables. Add all four settings to `.env.example`, **commented out**, with a line saying that leaving them unset disables that source and loses Brazilian coverage.

- [ ] **Step 5: Run the suite**

Run: `uv run pytest tests/sources/ -v`
Expected: PASS, contract test now covering four sources.

- [ ] **Step 6: Commit**

```bash
git add src/jobscout/sources/ tests/sources/ tests/fixtures/ src/jobscout/config.py .env.example
git commit -m "feat: add Adzuna and Jooble, the keyed Brazilian sources"
```

---

### Task 5: Turning the paragraph into search terms

**Files:**
- Create: `src/jobscout/matching/terms.py`
- Create: `tests/matching/test_terms.py`
- Modify: `src/jobscout/models/user.py`
- Modify: `src/jobscout/pipeline/users.py`

**Interfaces:**
- Produces: `ExtractedProfile` (pydantic: `terms: list[str]`, `titles: list[str]`, `seniority: list[str]`, `work_modes: list[str]`, `regions: list[str]`, `required_skills: list[str]`, `excluded_keywords: list[str]`); `extract_profile(paragraph: str, llm: BaseChatModel) -> ExtractedProfile`; `profile_hash(paragraph: str) -> str`.
- `UserPreferences` gains `search_terms: list[str]` (JSON) and `profile_hash: str | None`.

**Why this fills the structured fields and not only the terms:** `pipeline/filters.py` and `build_user_prompt()` already read `titles`, `regions`, `work_modes` and `excluded_keywords`. A paragraph-only flow leaves them empty, which makes the deterministic filter inert and strips the LLM prompt of its constraints. Spec §10.

- [ ] **Step 1: Write the failing tests** in `tests/matching/test_terms.py`

```python
def test_extraction_returns_ranked_terms_and_structured_fields(): ...  # fake LLM, known JSON
def test_terms_are_short(): ...               # each term is 1-3 words; a sentence is not a term
def test_an_empty_paragraph_raises_without_calling_the_llm(): ...      # Review Focus 4
def test_a_paragraph_yielding_no_terms_raises(): ...                   # Review Focus 4
def test_the_hash_is_stable_across_whitespace_only_changes(): ...
def test_the_hash_changes_when_the_words_change(): ...
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/matching/test_terms.py -v`

- [ ] **Step 3: Implement `extract_profile` and `profile_hash`**

Use the project's existing structured-output helper, the same way `matching/graph.py` gets structured evaluations — no direct vendor SDK call. Ask for terms ordered most-important first. An empty or term-less paragraph raises `ValueError`; the caller turns that into the run's error, so the system never searches for the empty string.

- [ ] **Step 4: Add the two `UserPreferences` columns and run the suite**

Run: `uv run pytest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/matching/terms.py tests/matching/test_terms.py src/jobscout/models/user.py src/jobscout/pipeline/users.py
git commit -m "feat: extract search terms and preferences from the profile paragraph"
```

---

### Task 6: The search run

**Files:**
- Create: `src/jobscout/pipeline/search.py`
- Create: `tests/pipeline/test_search.py`
- Modify: `src/jobscout/models/run.py` (add `"search"` to `RUN_JOBS`)

**Interfaces:**
- Consumes: `build_sources`, `source_statuses` (Task 1); `extract_profile`, `profile_hash` (Task 5); `ingest`, `run_match`, `select_candidates`.
- Produces: `run_search(session, settings, user_id, deps=None) -> SearchResult` with counters `fetched`, `sources_ok`, `sources_failed`, `candidates`, `evaluated`, `embedded`, `remaining`, `errors`.

**Behaviour, from spec §5.1:**
- Re-extract only when `profile_hash(paragraph)` differs from the stored hash; otherwise reuse the stored terms and make no LLM call.
- Top 3–5 terms per source, one page per term.
- A source that fails does not fail the run. The run is ok when at least one source succeeded, and not ok when all failed — the rule stage 4 settled for the digest.
- Scoring covers every active job with no match or a stale one, not only what this run fetched.
- The caps stop the run early; `remaining` records what is left and the next run resumes.
- Counters are written throughout, not only at the end.

- [ ] **Step 1: Write the failing tests** in `tests/pipeline/test_search.py`

```python
def test_an_unchanged_paragraph_reuses_terms_and_makes_no_llm_call(): ...
def test_a_changed_paragraph_re_extracts(): ...
def test_each_source_is_searched_with_the_top_terms(respx_mock): ...
def test_one_source_failing_does_not_fail_the_run(respx_mock): ...        # ok is True
def test_every_source_failing_fails_the_run(respx_mock): ...              # ok is False
def test_a_429_partway_keeps_what_was_already_fetched(respx_mock): ...    # Review Focus 3
def test_the_same_job_from_two_terms_is_counted_once(respx_mock): ...     # Review Focus 5
def test_an_empty_paragraph_writes_a_failed_run_and_fetches_nothing(): ...# Review Focus 4
def test_matches_are_committed_before_the_run_finishes(): ...
def test_a_capped_run_reports_what_remains_and_the_next_run_resumes(): ...
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/pipeline/test_search.py -v`

- [ ] **Step 3: Implement `run_search`**

Compose, do not reimplement: `ingest` for persistence, `run_match` for scoring. The only new logic is term selection, the per-source loop with its error isolation, and the counters.

- [ ] **Step 4: Run the suite**

Run: `uv run pytest -v`

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/pipeline/search.py tests/pipeline/test_search.py src/jobscout/models/run.py
git commit -m "feat: compose terms, fetching and scoring into one search run"
```

---

### Task 7: The API surface

**Files:**
- Create: `src/jobscout/api/routers/search.py`, `src/jobscout/api/routers/sources.py`
- Modify: `src/jobscout/api/routers/matches.py`, `src/jobscout/api/app.py`, `src/jobscout/scheduler.py`, `src/jobscout/models/match.py`
- Test: `tests/api/test_search.py`, `tests/api/test_sources.py`, `tests/api/test_matches.py`

**Interfaces:**
- Produces: `POST /search` → `{"run_id": int}`; `GET /search/{run_id}` → the run with its counters; `GET /sources` → the `SourceStatus` list; `PATCH /matches/{match_id}` with `{"status": "saved" | "dismissed" | "applied"}`.
- `MATCH_STATUSES` gains `"applied"`; it is terminal, like `dismissed` — staling never returns it (spec §10).

- [ ] **Step 1: Write the failing tests**

```python
def test_post_search_returns_a_run_id_immediately(): ...
def test_a_second_search_returns_the_run_already_in_flight(): ...
def test_get_search_reports_progress_counters(): ...
def test_get_sources_names_active_and_dormant_ones(): ...
def test_patch_sets_applied(): ...
def test_patch_rejects_an_unknown_status(): ...
def test_staling_does_not_revive_an_applied_match(): ...
def test_a_user_initiated_search_is_never_skipped_by_the_backoff(): ...
def test_dismissed_and_applied_are_hidden_from_the_default_listing(): ...
def test_they_are_returned_when_asked_for_by_status(): ...
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/api/ -v`

- [ ] **Step 3: Implement**

`POST /search` schedules `run_search` as an ad-hoc APScheduler job on the scheduler already in the lifespan — not a new thread, not `BackgroundTasks`, so there is one concurrency model against the SQLite file. If a search run for this user is unfinished, return it instead of starting another. The backoff governs scheduled runs only; a user-initiated search always runs.

Register both routers in `app.py`. Add `"applied"` to `MATCH_STATUSES`, leaving `REEVALUATABLE_STATUSES` untouched.

Exclude `dismissed` and `applied` from `match_listing_statement`'s default listing in `pipeline/run.py` (spec §10) — without this the user's "no" reappears on every search. Asking for them explicitly by `status` must still return them, the way `status="low"` already answers "why didn't this job show up".

- [ ] **Step 4: Run the suite**

Run: `uv run pytest -v`

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/api/ src/jobscout/models/match.py src/jobscout/scheduler.py tests/api/
git commit -m "feat: expose search, source status and match status over the API"
```

---

### Task 8: CLI, documentation and the live check

**Files:**
- Modify: `src/jobscout/cli.py`, `README.md`, `CLAUDE.md`, `.env.example`
- Modify: `docs/superpowers/specs/2026-09-19-jobscout-design.md` (the live parent spec)
- Test: `tests/test_cli.py`

**Interfaces:** `uv run jobscout search` runs one search synchronously and prints the ranked result.

- [ ] **Step 1: Write the failing test**

```python
def test_search_command_prints_ranked_matches(): ...
def test_search_command_reports_dormant_sources(): ...
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`

- [ ] **Step 3: Implement the command, then update the documentation**

`README.md`: a "Sources" section stating plainly which sources need no key and work immediately, which need a free key, and that **the keyed ones are what add Brazilian jobs**. Spec §2 requires this to be explicit rather than buried. Note that the scheduler is off by default and how to turn it on.

`CLAUDE.md`: current state becomes stage 5a; record that Arbeitnow is off by default, that `SOURCES` now defaults to four sources, and that the frontend decision changed from Reflex to static HTML served by FastAPI.

The **live parent spec**: §4 gains the new modules, §7 gains `applied`, `search_terms` and `profile_hash`. The stage-3 and stage-4 specs and anything under `plans/` are history — do not touch them.

- [ ] **Step 4: Full verification**

```bash
uv run pytest && uv run mypy src && uv run ruff check . && uv run ruff format --check . && uv lock --check
```

- [ ] **Step 5: The live check**

With a real LLM key and the Adzuna key in `.env`:

```bash
uv run jobscout search
```

Confirm ranked tech jobs come back, that Brazilian jobs appear among them, and that scores now exceed the old 0–35 band. **If they do not, that is the finding** — record the score distribution rather than adjusting the threshold to flatter it.

- [ ] **Step 6: Commit**

```bash
git add src/jobscout/cli.py README.md CLAUDE.md .env.example docs/ tests/test_cli.py
git commit -m "docs: document the sources and record the stage 5a outcome"
```

# Scraped sources and LinkedIn Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect LinkedIn, Indeed and Google Jobs postings through JobSpy as three ordinary sources, merge the copies one vacancy produces across sources, and search every source with the regions the user actually stored.

**Architecture:** A single adapter (`sources/jobspy_base.py`) turns `scrape_jobs()`'s DataFrame into `RawJob` rows and raises on the per-site errors JobSpy reports in `DataFrame.attrs` instead of letting a block look like an empty result. Three thin site modules subclass it and differ only in which search parameter they fill. `pipeline/search.py` starts populating `SearchQuery` from stored preferences and gives scraped sources a smaller term budget; `pipeline/ingest.py` gains a fingerprint merge in front of the existing upsert.

**Tech Stack:** Python 3.12, `uv`, SQLModel, pandas (arrives with `python-jobspy`), pytest. New dependency: `python-jobspy` (MIT).

**Spec:** `docs/superpowers/specs/2026-10-23-scraped-sources-and-linkedin-design.md`

**Scope:** this plan replaces Task 4 of `docs/superpowers/plans/2026-10-22-stage-5a-sources-and-search.md` (Adzuna is dropped, Jooble survives as Task 7 here). That plan's Tasks 7 and 8 — the API surface, CLI, documentation and live check — still stand and run after this one.

## Global Constraints

- **No proxy in the default path.** `JOBSPY_PROXIES` is empty by default and the project must run without it. If LinkedIn blocks a proxy-less run twice in a row, LinkedIn ships opt-in instead — never a paid dependency in the default.
- **The existing caps are untouched:** `max_embeddings_per_run=100`, `max_llm_evaluations_per_run=25`, `SIMILARITY_THRESHOLD=0.45`.
- Scraped sources: `jobspy_results_wanted=10`, `jobspy_max_terms=3`, `jobspy_hours_old=168`. Keyless API sources keep `MAX_TERMS_PER_SOURCE = 5`.
- `fetch_description=True` on LinkedIn. There is no description back-fill module: JobSpy has no public per-job call.
- No test touches the network, an LLM or a real clock. The three scraped sources patch `scrape_jobs`; every other source keeps `respx`. **No fixture is hand-written** — the scraped fixtures come from the capture command in Task 2, run by the user.
- `sources/` does no DB work and imports nothing from `pipeline/`. `pipeline/` is the only composer.
- Operator config (proxy, volumes, enabled sources) lives in `Settings`. User preferences (regions, work modes) live in the DB. Never cross them.
- Every name in `Settings.sources` must exist in `SOURCE_FACTORIES`, or `build_sources` raises.
- `uv run pytest`, `uv run mypy src`, `uv run ruff check .`, `uv run ruff format --check .` clean before every commit.
- English for code, comments and docs. Commit messages end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>` on its own line in the body.

## Review Focus

Five conditions the spec implies that no happy path exercises. Each has a test assigned to the task that owns the code.

1. **A site is blocked and JobSpy reports it in `attrs["errors"]`** while returning an empty DataFrame and no exception. Expected: the source raises, the run names it, and the other sources still produce results. This is the common case, not the exception, and getting it wrong means every block is logged as "0 jobs, no errors". (Task 2)
2. **One vacancy arrives from two sources** (LinkedIn and Google). Expected: one row; the second sighting refreshes `last_seen_at` and appends the second source under `raw["duplicates"]` without overwriting the first source's payload, which `pipeline/repair.py` re-renders the description from. (Task 6)
3. **The same title and company in two different cities.** Expected: two rows. This is why the user put location in the fingerprint; collapsing them would silently delete real vacancies. (Task 6)
4. **A stored region JobSpy does not recognise** ("remoto", "Europe", ""). Expected: Indeed is searched as `worldwide` and the unmapped value is named in the run's errors — never a crash, and never a silently wrong country. (Task 4)
5. **A posting with no `id` or no `company`** — both optional in `JobPost`, both required by `RawJob`. Expected: `external_id` falls back to a hash of `job_url`, a missing company becomes an empty string, and only a row without `title` or `job_url` is skipped and named. (Task 2)

---

### Task 1: Settings for the scraped sources, and the broken default

**Files:**
- Modify: `src/jobscout/config.py:19` (the `sources` default) and the settings block
- Modify: `.env.example:7`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.jobspy_proxies: str | None`, `Settings.jobspy_results_wanted: int`, `Settings.jobspy_max_terms: int`, `Settings.jobspy_hours_old: int`, and the property `Settings.jobspy_proxy_list -> list[str]`.

- [ ] **Step 1: Write the failing tests** in `tests/test_config.py`

```python
def test_the_default_sources_are_all_registered():
    from jobscout.sources.registry import SOURCE_FACTORIES
    assert set(Settings(_env_file=None).source_names) <= set(SOURCE_FACTORIES)

def test_no_proxy_is_configured_by_default():
    assert Settings(_env_file=None).jobspy_proxy_list == []

def test_proxies_are_split_and_stripped():
    settings = Settings(_env_file=None, jobspy_proxies="user:pass@host:1, localhost ,")
    assert settings.jobspy_proxy_list == ["user:pass@host:1", "localhost"]

def test_the_scraped_volume_defaults_are_the_polite_ones():
    settings = Settings(_env_file=None)
    assert (settings.jobspy_results_wanted, settings.jobspy_max_terms) == (10, 3)
    assert settings.jobspy_hours_old == 168
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `jobspy_proxy_list` does not exist, and the default `sources` string names `adzuna` and `jooble`, which are not registered.

- [ ] **Step 3: Implement the four fields and the property in `src/jobscout/config.py`**

`ge=1` on the three integers, for the reason the scheduler intervals already carry it. Set `sources` to `"himalayas,remotive"` — Task 3 adds the scraped names and Task 7 adds `jooble`, each as it registers them.

- [ ] **Step 4: Update `.env.example`**

Replace `SOURCES=arbeitnow` with `SOURCES=himalayas,remotive`, and add a commented block for the four new variables: that a proxy is optional and paid, that the volumes are what keeps a proxy-less clone from being blocked, and the `JOBSPY_PROXIES` format (`user:pass@host:port`, comma-separated).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest && uv run mypy src && uv run ruff check . && uv run ruff format --check .`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/jobscout/config.py .env.example tests/test_config.py
git commit -m "feat: add the JobSpy settings and fix the unregistered source default"
```

---

### Task 2: The JobSpy adapter

**Files:**
- Create: `src/jobscout/sources/jobspy_base.py`
- Create: `tests/fixtures/linkedin_sample.jsonl` (captured, see Step 1)
- Create: `tests/sources/test_jobspy_base.py`
- Modify: `pyproject.toml` (the dependency and the mypy override)

**Interfaces:**
- Consumes: `Settings` from Task 1.
- Produces:
  - `class SourceBlocked(RuntimeError)` — raised when JobSpy reports a per-site error.
  - `to_raw_jobs(frame: pd.DataFrame, source: str) -> list[RawJob]`
  - `class JobSpySource` with `name: str`, `site: str`, `supports_search = True`, `term_budget: int | None`, `fetch_description: bool = False`, `warnings: list[str]`, `__init__(self, settings: Settings)`, `search_kwargs(self, query: SearchQuery) -> dict[str, object]` (the hook the three site modules override), and `fetch(self, query: SearchQuery) -> list[RawJob]`.
  - `warnings` is an instance list, cleared at the start of every `fetch` and filled from `frame.attrs["warnings"]` plus whatever the subclass wants reported. It is how a non-fatal problem reaches the run without a source raising or a protocol change; Task 4 drains it.

- [ ] **Step 1: Add the dependency, then ask the user to capture the fixture**

```bash
uv add python-jobspy
```

The fixture must come from a real call, and §10 of the spec says the user runs anything that scrapes from their own IP. Give them this command and wait for the file:

```bash
uv run jobspy "python developer" --site linkedin --location Brazil \
  --fetch-description -n 5 -o tests/fixtures/linkedin_sample.jsonl
```

**Do not proceed without it, and do not write the fixture by hand.** If LinkedIn blocks the capture, stop and report it: that is the §12 finding that flips LinkedIn to opt-in, not something to work around.

- [ ] **Step 2: Write the failing tests** in `tests/sources/test_jobspy_base.py`

A `_frame(rows, errors=None)` helper builds a DataFrame from the captured rows and sets `frame.attrs = {"errors": errors or {}, "warnings": {}}`. Tests patch `jobscout.sources.jobspy_base.scrape_jobs` with `monkeypatch`.

```python
def test_a_captured_row_becomes_a_raw_job():
    jobs = to_raw_jobs(_frame(load_jsonl("linkedin_sample.jsonl")), "linkedin")
    assert jobs and all(j.source == "linkedin" and j.url and j.description for j in jobs)
    assert all("<" not in j.description for j in jobs)

def test_a_row_without_an_id_falls_back_to_the_url():
    [job] = to_raw_jobs(_frame([_row(id=None, job_url="https://x/1")]), "linkedin")
    assert job.external_id and job.external_id != "None"

def test_two_rows_without_ids_do_not_collide():
    jobs = to_raw_jobs(_frame([_row(id=None, job_url="https://x/1"),
                               _row(id=None, job_url="https://x/2")]), "linkedin")
    assert len({j.external_id for j in jobs}) == 2

def test_a_row_without_a_company_is_kept():
    [job] = to_raw_jobs(_frame([_row(company=None)]), "linkedin")
    assert job.company == ""

def test_a_row_without_a_title_or_url_is_skipped():
    assert to_raw_jobs(_frame([_row(title=None), _row(job_url=None)]), "linkedin") == []

def test_a_blocked_site_raises_instead_of_returning_nothing(monkeypatch):
    monkeypatch.setattr(jobspy_base, "scrape_jobs",
                        lambda **kw: _frame([], errors={"linkedin": "429"}))
    with pytest.raises(SourceBlocked, match="429"):
        JobSpySource(Settings(_env_file=None)).fetch(SearchQuery(keywords=["python"]))

def test_the_settings_reach_scrape_jobs(monkeypatch):
    seen = {}
    monkeypatch.setattr(jobspy_base, "scrape_jobs",
                        lambda **kw: seen.update(kw) or _frame([]))
    JobSpySource(Settings(_env_file=None, jobspy_proxies="localhost")).fetch(
        SearchQuery(keywords=["python"]))
    assert seen["results_wanted"] == 10 and seen["hours_old"] == 168
    assert seen["proxies"] == ["localhost"]

def test_no_keyword_means_no_call(monkeypatch):
    monkeypatch.setattr(jobspy_base, "scrape_jobs", _never_called)
    assert JobSpySource(Settings(_env_file=None)).fetch(SearchQuery()) == []
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/sources/test_jobspy_base.py -v`
Expected: FAIL on the import of `jobscout.sources.jobspy_base`.

- [ ] **Step 4: Implement `src/jobscout/sources/jobspy_base.py`**

`fetch` calls `scrape_jobs(site_name=[self.site], results_wanted=…, hours_old=…, proxies=…, description_format="markdown", fetch_description=self.fetch_description, **self.search_kwargs(query))`, raises `SourceBlocked` when `frame.attrs["errors"]` is non-empty, and otherwise returns `to_raw_jobs(frame, self.name)`. One query per call: the composer passes one term at a time, as it already does for the API sources.

The mapping decisions, which the tests pin:
- `external_id = row["id"] or sha256(job_url)` hexdigest.
- `description` through `jobscout.sources.text.html_to_text`, to hold the plain-text invariant the generic contract test asserts even though the format requested is markdown.
- `company or ""`; a row missing `title` or `job_url` is logged and skipped, the way `himalayas._fetch_with` already skips a malformed item.
- `remote` from `is_remote`, `posted_at` from `date_posted`, salary from `min_amount`/`max_amount`/`currency`, `raw` from the row itself. NaN is not None: convert through pandas before use.

- [ ] **Step 5: Add the mypy override in `pyproject.toml`**

`[[tool.mypy.overrides]]` with `module = ["jobspy.*", "pandas.*"]` and `ignore_missing_imports = true`. CI runs mypy strict, so without this the new module cannot pass.

- [ ] **Step 6: Run the tests and the gates**

Run: `uv run pytest tests/sources/test_jobspy_base.py -v && uv run mypy src`
Expected: PASS and clean.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/jobscout/sources/jobspy_base.py tests/
git commit -m "feat: adapt JobSpy results to RawJob, and raise on a blocked site"
```

---

### Task 3: The three sites, the registry and the contract test

**Files:**
- Create: `src/jobscout/sources/linkedin.py`, `src/jobscout/sources/indeed.py`, `src/jobscout/sources/google.py`
- Create: `tests/fixtures/indeed_sample.jsonl`, `tests/fixtures/google_sample.jsonl` (captured, as in Task 2 Step 1, with `--site indeed` and `--site google`)
- Modify: `src/jobscout/sources/registry.py`, `src/jobscout/config.py` (the `sources` default)
- Modify: `tests/sources/test_contract.py`
- Test: `tests/sources/test_scraped_sources.py`

**Interfaces:**
- Consumes: `JobSpySource`, `to_raw_jobs`, `SourceBlocked` from Task 2.
- Produces: `LinkedInSource`, `IndeedSource`, `GoogleSource`; `country_for(regions: list[str]) -> tuple[str, str | None]` in `indeed.py`, returning the JobSpy country and the unrecognised value it had to ignore.

- [ ] **Step 1: Write the failing tests** in `tests/sources/test_scraped_sources.py`

```python
def test_each_site_is_registered_and_needs_no_credential():
    settings = Settings(_env_file=None, sources="linkedin,indeed,google")
    assert [s.name for s in build_sources(settings)] == ["linkedin", "indeed", "google"]
    assert all(s.active for s in source_statuses(settings))

def test_linkedin_asks_for_descriptions_and_the_others_do_not():
    settings = Settings(_env_file=None)
    assert LinkedInSource(settings).fetch_description is True
    assert IndeedSource(settings).fetch_description is False

def test_google_uses_its_own_search_parameter():
    kwargs = GoogleSource(Settings(_env_file=None)).search_kwargs(SearchQuery(keywords=["ml"]))
    assert kwargs == {"google_search_term": "ml"}

def test_indeed_maps_a_region_to_a_country():
    assert country_for(["Brasil"]) == ("brazil", None)
    assert country_for(["Brazil", "Portugal"]) == ("brazil", None)   # first wins

def test_an_unmapped_region_falls_back_to_worldwide_and_says_so():
    assert country_for(["remoto"]) == ("worldwide", "remoto")
    assert country_for([]) == ("worldwide", None)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/sources/test_scraped_sources.py -v`
Expected: FAIL on the imports.

- [ ] **Step 3: Implement the three site modules**

Each is a subclass of `JobSpySource` setting `name`, `site` and, for LinkedIn, `fetch_description = True`; `term_budget` returns `settings.jobspy_max_terms`. `GoogleSource.search_kwargs` fills `google_search_term`, the only parameter Google filters on. `IndeedSource.search_kwargs` fills `search_term` and `country_indeed` from `country_for(query.locations)`, and names an unrecognised region through a `logging.warning` **and** by raising nothing — the composer reports it (Task 4).

`country_for` maps a small table of names the project actually meets to JobSpy's country values — at minimum Brazil (`brasil`, `brazil`, `br`), Portugal, Spain, the USA, the UK, Germany and Canada — case-insensitively and accent-insensitively, and returns `("worldwide", value)` for anything else. When it returns an ignored value, `IndeedSource.search_kwargs` appends a sentence naming it to `self.warnings`, which is what carries it to the run in Task 4.

- [ ] **Step 4: Register the sources and extend the default**

Add the three factories to `SOURCE_FACTORIES`. They need no entry in `SOURCE_MISSING_CREDENTIALS`: the proxy is optional, so its absence must not make a source dormant. Set `Settings.sources` to `"himalayas,remotive,linkedin,indeed,google"` and update `.env.example` to match.

- [ ] **Step 5: Teach the contract test about a non-HTTP source**

`SOURCE_HTTP_FIXTURES` can only describe a source that `respx` can intercept. Replace it with one mapping whose values are either an HTTP fixture (url, filename) or a JobSpy fixture (filename), and have the test patch `scrape_jobs` for the second kind and mock the URL for the first. Every assertion already in the test — `external_id`, `title`, `url`, `description` present, ids unique, description plain — must still run for all six sources, unchanged.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/sources -v`
Expected: PASS, including `test_source_contract` parametrized over six sources.

- [ ] **Step 7: Commit**

```bash
git add src/jobscout/sources tests/ src/jobscout/config.py .env.example
git commit -m "feat: add the LinkedIn, Indeed and Google sources"
```

---

### Task 4: Searching with the user's regions, and a smaller budget for scraped sources

**Files:**
- Modify: `src/jobscout/sources/base.py` (the `JobSource` protocol)
- Modify: `src/jobscout/pipeline/search.py` (`_queries_for`, `_fetch`)
- Test: `tests/pipeline/test_search.py`

**Interfaces:**
- Consumes: `term_budget` from Tasks 2–3.
- Produces: `_queries_for(source: JobSource, terms: list[str], prefs: UserPreferences) -> list[SearchQuery]`; `JobSource.term_budget: int | None` (None means `MAX_TERMS_PER_SOURCE`).

- [ ] **Step 1: Write the failing tests** in `tests/pipeline/test_search.py`

```python
def test_a_search_query_carries_the_stored_regions_and_work_modes():
    prefs = UserPreferences(regions=["Brasil"], work_modes=["remote"])
    [query] = _queries_for(_FakeSource(supports_search=True, term_budget=1), ["python"], prefs)
    assert query.locations == ["Brasil"] and query.remote_only is True

def test_a_scraped_source_gets_fewer_terms_than_an_api_source():
    terms = ["a", "b", "c", "d", "e"]
    prefs = UserPreferences()
    assert len(_queries_for(_FakeSource(term_budget=3), terms, prefs)) == 3
    assert len(_queries_for(_FakeSource(term_budget=None), terms, prefs)) == 5

def test_a_catalogue_source_is_still_asked_once():
    assert _queries_for(_FakeSource(supports_search=False), ["a", "b"], UserPreferences()) == [
        SearchQuery()
    ]

def test_an_unmapped_region_is_named_in_the_run(session, settings):
    # regions=["remoto"], one fake scraped source; the run is ok and errors name the value
    result = run_search(session, settings, user_id=1, deps=_fake_deps())
    assert result.ok and any("remoto" in e for e in result.errors)

def test_a_block_on_the_second_term_keeps_the_first_term_jobs(session, settings):
    # a fake source that answers "python", then raises SourceBlocked("429") on "sql"
    result = run_search(session, settings, user_id=1, deps=_fake_deps())
    assert result.fetched == 1 and result.sources_ok == 1
    assert any("429" in e for e in result.errors)
    assert session.exec(select(Job)).all(), "what was fetched before the block is kept"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/pipeline/test_search.py -v`
Expected: FAIL — `_queries_for` takes no `prefs`, and `term_budget` does not exist on the protocol.

- [ ] **Step 3: Implement**

Add `term_budget: int | None` to the `JobSource` protocol with a comment that `None` means the shared default, and give the existing sources the default. `_queries_for` fills `locations` from `prefs.regions` and `remote_only` from `prefs.work_modes` containing a remote mode, and slices the terms by `source.term_budget or MAX_TERMS_PER_SOURCE`. `_fetch` already has `prefs` in the caller; pass it through rather than re-reading it.

Carrying a non-fatal problem into the run: after a source's terms are done, `_fetch` drains `getattr(source, "warnings", ())` into `result.errors`, deduplicated, in the same `f"{source.name}: …"` shape the existing failures use. `getattr` rather than a protocol field, because only the scraped sources have anything to say and the protocol should not grow a member five of six implementations ignore. A warning that reaches only the log is not enough — the page reads the run.

The 429-on-the-second-term behaviour needs no new code: `SourceBlocked` reaches `ingest` as any exception does, `outcome.error` is set, and `_fetch` already breaks out of the term loop while counting the source as `ok` because it answered once. The test above pins that this stays true for a source that raises mid-loop.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/pipeline -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/sources/base.py src/jobscout/pipeline/search.py tests/
git commit -m "feat: search with the user's regions and a smaller scraped budget"
```

---

### Task 5: Score the freshest candidates first

**Files:**
- Modify: `src/jobscout/pipeline/matching.py:57-79` (`select_candidates`)
- Test: `tests/pipeline/test_matching.py`

**Interfaces:**
- Produces: `select_candidates` unchanged in signature, now ordered.

- [ ] **Step 1: Write the failing test** in `tests/pipeline/test_matching.py`

```python
def test_candidates_come_back_newest_first_with_undated_jobs_last(session):
    # three active jobs: posted_at = yesterday, posted_at = today, posted_at = None
    candidates = select_candidates(session, UserPreferences(), user_id=1)
    assert [j.title for j in candidates] == ["today", "yesterday", "undated"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/pipeline/test_matching.py::test_candidates_come_back_newest_first_with_undated_jobs_last -v`
Expected: FAIL — selection has no order today, so the rows come back in insertion order.

- [ ] **Step 3: Implement**

Order the statement by `posted_at` descending with nulls last, then `first_seen_at` descending as the tie-break, so a source that gives no date still sorts by when JobScout met it. The caps spend the user's own LLM key: whatever the 25 evaluations go to should be the freshest thing available, not whatever the database returned first.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/pipeline -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/pipeline/matching.py tests/pipeline/test_matching.py
git commit -m "feat: score the freshest candidates first"
```

---

### Task 6: One vacancy, one row — the fingerprint merge

**Files:**
- Modify: `src/jobscout/models/job.py`
- Modify: `src/jobscout/pipeline/ingest.py`
- Modify: `README.md:80-95` (the "Upgrading an existing database" section)
- Test: `tests/pipeline/test_ingest.py`

**Interfaces:**
- Produces: `Job.fingerprint: str | None` (indexed); `fingerprint(title: str, company: str, location: str | None) -> str` in `pipeline/ingest.py`; `UpsertStats.merged: int` and `IngestResult.merged: int`.

- [ ] **Step 1: Write the failing tests** in `tests/pipeline/test_ingest.py`

```python
def test_the_same_vacancy_from_two_sources_is_one_row(session):
    upsert_jobs(session, [_raw(source="linkedin", title="Dev Python", company="Acme",
                               location="São Paulo, SP, BR")])
    stats = upsert_jobs(session, [_raw(source="google", title="dev  python", company="ACME",
                                       location="Sao Paulo, Brazil")])
    assert stats.created == 0 and stats.merged == 1
    [job] = session.exec(select(Job)).all()
    assert job.source == "linkedin"
    assert job.raw["duplicates"] == [{"source": "google", "external_id": ANY, "url": ANY}]

def test_the_first_source_payload_is_never_overwritten(session):
    # repair.py re-renders the description from `raw`; a merge must not replace it
    ...
    assert job.raw["description"] == "<p>the linkedin html</p>"

def test_the_same_role_in_two_cities_stays_two_rows(session):
    stats = upsert_jobs(session, [_raw(location="São Paulo, SP, BR"),
                                  _raw(location="Rio de Janeiro, RJ, BR")])
    assert stats.created == 2

def test_a_row_without_a_location_merges_only_with_another_without_one(session): ...

def test_rows_with_no_fingerprint_yet_never_merge(session):
    # an existing row written before this task (fingerprint IS NULL) is left alone
    ...
    assert stats.created == 1 and stats.merged == 0

def test_ingesting_the_same_data_twice_is_still_a_no_op(session):
    first = upsert_jobs(session, [_raw()])
    second = upsert_jobs(session, [_raw()])
    assert (second.created, second.changed, second.merged) == (0, 0, 0)
    assert second.updated == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/pipeline/test_ingest.py -v`
Expected: FAIL — `Job` has no `fingerprint` and `UpsertStats` has no `merged`.

- [ ] **Step 3: Implement the column and the fingerprint function**

`fingerprint` normalises each part — NFKD, accents dropped, lowercased, every run of non-alphanumerics collapsed to one space, stripped — takes **only the first comma-separated component of the location** (so `São Paulo, SP, BR` and `Sao Paulo, Brazil` agree on `sao paulo`, which is what makes a cross-source merge actually fire), joins the three with `|` and returns a sha256 hexdigest.

- [ ] **Step 4: Implement the merge in `upsert_jobs`**

Only for a raw job whose `(source, external_id)` is new: look up an existing row by fingerprint; if one exists, refresh its `last_seen_at`/`is_active`, append `{"source", "external_id", "url"}` to the list under `raw["duplicates"]` (re-assigning `job.raw` so SQLAlchemy sees the change), count `merged`, and create no row. Never touch the other `_METADATA_FIELDS`, the title, the description or the hash — the first source owns the payload. A null fingerprint on either side never merges.

This amends the ingest invariant named in `CLAUDE.md`: the upsert is still keyed on `(source, external_id)`, with the fingerprint merge in front of it. Idempotence is unchanged — a second identical ingest is still `updated`, not `merged`.

- [ ] **Step 5: Document the migration in `README.md`**

In the existing "Upgrading an existing database" section, add the `ALTER TABLE job ADD COLUMN fingerprint VARCHAR;`, the `CREATE INDEX ix_job_fingerprint ON job (fingerprint);` and a one-line back-fill note, with the same explanation of why the index is not optional that the stage 4 block already carries.

- [ ] **Step 6: Run the tests and the gates**

Run: `uv run pytest && uv run mypy src && uv run ruff check . && uv run ruff format --check .`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add src/jobscout/models/job.py src/jobscout/pipeline/ingest.py README.md tests/
git commit -m "feat: merge one vacancy arriving from several sources"
```

---

### Task 7: Jooble — blocked on the key

**Files:**
- Create: `src/jobscout/sources/jooble.py`
- Create: `tests/fixtures/jooble_search.json` (captured from the live API)
- Modify: `src/jobscout/sources/registry.py`, `src/jobscout/config.py`, `.env.example`
- Test: `tests/sources/test_jooble.py`, `tests/sources/test_contract.py`

**Interfaces:**
- Produces: `JoobleSource` with `name = "jooble"`, `supports_search = True`, `BASE_URL`; a `SOURCE_MISSING_CREDENTIALS["jooble"]` entry naming `JOOBLE_API_KEY`.

- [ ] **Step 1: Stop if there is no key**

The user said they would register one. Without `JOOBLE_API_KEY` **and** a response captured from the live API, this task does not start: the stage 5a plan forbids hand-written fixtures, and a guessed request shape is worse than a missing source. Report it and move to Task 8; the other five sources do not depend on this one.

- [ ] **Step 2: Confirm the request shape against the official docs, then capture the fixture**

Third-party sources disagree on GET versus POST and on the host (`jooble.org` versus `us.jooble.org`). Read the docs behind the registered account, then capture one response to `tests/fixtures/jooble_search.json`.

- [ ] **Step 3: Write the failing tests** in `tests/sources/test_jooble.py`

The shape the other keyed-source tests use: the captured fixture through `respx`, asserting the mapped `RawJob` fields, that the keyword reaches the request as the API expects it, and that a malformed posting in the response is skipped rather than failing the fetch.

- [ ] **Step 4: Run to verify they fail**, then implement, following `himalayas.py`'s structure — injected `httpx.Client`, `_to_raw` static method, `html_to_text` on the description.

- [ ] **Step 5: Register it, add it to the default and to `.env.example`**, with the credential entry so a missing key makes it dormant instead of failing the run.

- [ ] **Step 6: Run the tests and the gates**, then commit.

```bash
git commit -m "feat: add the Jooble source"
```

---

### Task 8: Make the documentation stop contradicting the code

**Files:**
- Modify: `CLAUDE.md`, `AGENTS.md`
- Modify: `docs/superpowers/specs/2026-10-22-stage-5-sources-and-dashboard-design.md`
- Modify: `README.md`

- [ ] **Step 1: Rewrite the four "no scraping" claims**

In `CLAUDE.md` and `AGENTS.md`: the *What the project is* sentence ("never scraping"), and the roadmap, where stage 7's hosted demo is dropped and stage 5 names the scraped sources. In the stage 5 spec: §2's "Scraping — still forbidden" row, §3.1's and §9's Adzuna, §3.2's LinkedIn rejection, and §11. Each gets a pointer to `2026-10-23-scraped-sources-and-linkedin-design.md` rather than a quiet edit — the reversal is dated and attributed, so a reader of the old text can follow it.

- [ ] **Step 2: Write the README's source section and its honesty paragraph**

A table of the six sources saying for each whether it is a documented API or scraped through JobSpy, and a paragraph stating plainly that LinkedIn, Indeed and Google are collected by scraping, that this violates those sites' terms of use, that these sources can break whenever a page changes, and that `JOBSPY_PROXIES` is optional and paid. Someone who clones this runs it from their own IP; they learn that here, before the first run.

- [ ] **Step 3: Write the live check instructions for the user**

The exact `uv run jobscout fetch`/`match` sequence, what a healthy run's counters look like, and what a block looks like in `GET /runs` — so the user can run §12's check from their own connection and report back. State the fallback: blocked twice in a row means LinkedIn moves out of the default `SOURCES` and the README says why.

- [ ] **Step 4: Run the gates and commit**

```bash
git add CLAUDE.md AGENTS.md README.md docs/
git commit -m "docs: record that scraped sources are in, and the demo is out"
```

---

## Done when

`uv run pytest`, `uv run mypy src`, `uv run ruff check .` and `uv run ruff format --check .` are clean, CI is green, and the user's live check reports ranked LinkedIn, Indeed, Google, Himalayas and Remotive jobs for their own profile paragraph with no proxy configured — or reports a block twice in a row, in which case LinkedIn moves to opt-in and that finding is recorded instead.

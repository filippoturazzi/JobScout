# Saved Searches and the Conversation (backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give JobScout several saved searches per user, each built by a short deterministic conversation over one LLM reading of a paragraph, each with its own preferences, fetched jobs, matches and runs, and expose all of it through the API and CLI the page (next plan) will use.

**Architecture:** A `Search` row sits under the `User`; `UserPreferences`, `Match` and search `Run`s gain `search_id`, and a `SearchJob` table records which search fetched which job so a search scores only its own postings. The conversation is a pure module (`pipeline/conversation.py`) over a pydantic `Conversation` stored as JSON on the `Search`; `pipeline/searches.py` persists it and turns a confirmed summary into preferences. Runs go through the scheduler, which allows one search at a time per instance. A one-time `jobscout upgrade-db` rebuilds an existing SQLite database into the new shape.

**Tech Stack:** Python 3.12, SQLModel/SQLAlchemy, FastAPI, Typer, APScheduler, LangChain structured output, pytest + respx.

**Spec:** `docs/superpowers/specs/2026-11-07-chat-interface-design.md`. It covers the page as well; the page is the **next** plan. This plan builds everything in spec §5–§8 except the HTML/CSS/JS, and moves nothing into `src/jobscout/web/`.

## Global Constraints

- Dependencies point downward only: `sources` (no DB) · `matching` (no HTTP, no sources) · `pipeline` composes · `api`, `cli`, `scheduler` are thin shells. `db.py` must not import `pipeline`.
- Operator config stays in `Settings`/env; user data in the DB. No API key is ever returned or accepted by the API — only "found: true/false".
- LangGraph stays limited to `matching/graph.py`. The conversation is plain Python.
- Everything stays keyed by `user_id`; `api/deps.py::get_current_user()` remains the one auth seam. A search is a second key below the user.
- No LLM-written chat text: the conversation returns structured data (question ids, option choices, values); the page fills fixed strings.
- At most five numbered questions: role (1), level (2), work modes (3), location (4, which may take a country step and a city step), skills (5).
- Level Intern or Junior adds exactly `senior, sr, lead, staff, principal` to `excluded_keywords`.
- Extraction never writes preferences; only confirming ("Search jobs") does. A clicked answer always beats a later reading.
- A search scores only jobs its own runs fetched. One search runs at a time per instance.
- TDD; no test touches the network or a real LLM (use `tests/matching/fakes.py`, respx, fake sources).
- Before every commit: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest` all clean.
- English for code, comments, docs.

## Review Focus

1. **Running the app on an un-upgraded database** — the user pulls, runs `jobscout serve`, and must get one sentence telling them to back up and run `jobscout upgrade-db`, not a SQL traceback; the upgrade must keep applied/dismissed verdicts. Pinned in Task 7 (`test_init_db_refuses_an_old_database`, `test_upgrade_keeps_matches_with_their_status_and_ids`).
2. **A refinement that contradicts a clicked answer, or adds a new need** — "actually hybrid" after the user clicked Remote keeps Remote; "hybrid in Brazil" with no clicked mode now asks the city. Pinned in Task 5 (`test_a_clicked_answer_beats_a_new_reading`, `test_a_reading_that_adds_hybrid_asks_for_the_city`).
3. **The extraction call failing on the first paragraph** (free-tier 429) — the search must still exist, keep the paragraph, carry the error, and recover on retry. Pinned in Task 6 (`test_a_failed_reading_keeps_the_search_and_its_paragraph`, `test_reread_clears_the_error`).
4. **Starting a second search while one runs, or deleting the running one** — refused with a clear 409, never a duplicate run or a half-deleted search. Pinned in Task 8 and Task 10 (`test_starting_another_search_while_one_runs_is_refused`, `test_deleting_the_running_search_is_refused`).
5. **City matching with accents and state codes** — city "São Paulo" must accept "Sao Paulo, SP, Brazil" and a bare "Brazil", and reject "Rio de Janeiro, RJ, Brazil". Pinned in Task 3 (`test_city_rule`, parametrized).

---

### Task 1: Re-key preferences, matches and runs by search

Mechanical but wide: every pipeline function that took `user_id` to find preferences now takes `search_id`. Shells that do not know a search yet use `get_or_create_default_search` until Tasks 10–11 replace them.

**Files:**
- Create: `tests/fixtures/schema_pre_searches.sql`, `src/jobscout/models/search.py`, `src/jobscout/pipeline/searches.py`, `tests/helpers.py`, `tests/pipeline/test_searches.py`
- Modify: `src/jobscout/models/{user,match,run,__init__}.py`, `src/jobscout/pipeline/{users,matching,run,search,digest}.py`, `src/jobscout/scheduler.py`, `src/jobscout/cli.py`, `src/jobscout/api/routers/{preferences,search,matches,jobs}.py`, and every test that builds preferences (`tests/pipeline/*`, `tests/api/*`, `tests/test_cli.py`, `tests/test_scheduler.py`, `tests/test_match_model.py`)

**Interfaces:**
- Produces:
  - `models.Search(id, user_id: int FK user.id indexed, title: str, conversation: dict JSON default {}, last_used_at: datetime indexed default utcnow, created_at, updated_at)`, exported from `jobscout.models`.
  - `UserPreferences.search_id: int` (FK `search.id`, unique, indexed); `user_id` keeps its index but **loses `unique`**. `"search_id"` joins `PROTECTED_PREFERENCE_FIELDS`.
  - `Match.search_id: int` (FK `search.id`, indexed); constraint `UniqueConstraint("job_id", "search_id", name="uq_match_job_search")` replaces `uq_match_job_user`; index `ix_match_search_status(search_id, status)` added; `user_id` stays (ownership, user-wide listings).
  - `Run.search_id: int | None` (indexed, no FK so history survives a deleted search).
  - `pipeline.searches`: `class SearchNotFoundError(LookupError)`; `add_search(session, user_id: int, title: str, paragraph: str = "") -> Search` (also inserts its `UserPreferences` with `profile_summary=paragraph`); `get_search(session, user_id: int, search_id: int) -> Search` (raises `SearchNotFoundError` when absent or another user's); `list_searches(session, user_id) -> list[Search]` (newest `last_used_at` first, id desc tie-break); `latest_search(session, user_id) -> Search | None`; `get_or_create_default_search(session, user_id) -> Search` (latest, else `add_search(..., title="My search")`); `touch(session, search: Search) -> None` (sets `last_used_at`, commits); `delete_search(session, user_id, search_id) -> None` (deletes its matches and preferences, then the search; jobs stay).
  - New signatures (first id argument is now the search): `get_preferences(session, search_id)`, `update_preferences(session, search_id, changes)`, `select_candidates(session, prefs, search_id, first_seen_after=None)`, `run_match(session, settings, search_id, ...)` (reads `user_id`/locale through the `Search`), `list_jobs(session, search_id, ...)`, `match_listing_statement(search_id, ...)`, `list_matches(session, search_id, ...)`, `save_preferences(session, settings, search_id, changes, ...)` (stales only that search's matches), `open_search_run(session, search_id) -> Run` (sets both `user_id` and `search_id`), `run_search(session, settings, search_id, ...)`.
  - `get_or_create_default_user` no longer creates a `UserPreferences` row.
  - `tests/helpers.py`: `make_search(session, paragraph: str = "", title: str = "Test search", **prefs) -> Search` (default user + `add_search` + `update_preferences` with `prefs`).

- [ ] **Step 1: Capture today's schema for the upgrade test (Task 7) before any model changes**

Run:
```bash
uv run python -c "from sqlalchemy.schema import CreateTable, CreateIndex; from sqlalchemy.dialects import sqlite; from sqlmodel import SQLModel; import jobscout.models; d=sqlite.dialect(); print('\n'.join(str(CreateTable(t).compile(dialect=d)).strip()+';' + ''.join('\n'+str(CreateIndex(i).compile(dialect=d))+';' for i in t.indexes) for t in SQLModel.metadata.sorted_tables))" > tests/fixtures/schema_pre_searches.sql
```
Expected: the file contains `CREATE UNIQUE INDEX ix_user_preferences_user_id` and `CREATE TABLE match` with `CONSTRAINT uq_match_job_user`. Commit it alone: `git commit -m "test: keep the pre-searches schema for the upgrade test"`.

- [ ] **Step 2: Write the failing tests**

In `tests/pipeline/test_searches.py`:
```python
def test_add_search_creates_its_preferences(session):
    search = make_search(session, paragraph="AI engineer")
    assert get_preferences(session, search.id).profile_summary == "AI engineer"

def test_latest_search_is_the_most_recently_used(session): ...  # touch() the older one; latest_search returns it
def test_get_search_refuses_another_users_search(session): ...  # pytest.raises(SearchNotFoundError)
def test_delete_search_removes_its_preferences_and_matches_but_not_jobs(session): ...
def test_get_or_create_default_search_reuses_the_latest(session): ...  # second call returns same id; no new row
def test_default_user_has_no_preferences_until_a_search_exists(session): ...
```
In `tests/test_match_model.py`: `test_the_same_job_can_be_scored_by_two_searches` (two `Match` rows, same `job_id`, different `search_id`, commit succeeds) and `test_one_search_cannot_score_a_job_twice` (`pytest.raises(IntegrityError)`).
In `tests/pipeline/test_matching.py`: `test_run_match_writes_matches_for_the_search` — after `run_match(session, settings, search.id, deps=...)`, every `Match` has `search_id == search.id` and `user_id == search.user_id`; a second search's `list_matches` is empty.

- [ ] **Step 3: Run them and see them fail**

Run: `uv run pytest tests/pipeline/test_searches.py tests/test_match_model.py tests/pipeline/test_matching.py -v`
Expected: FAIL (`ImportError: cannot import name 'Search'`).

- [ ] **Step 4: Implement the models, `pipeline/searches.py`, and the signature changes listed under Interfaces**

Shells keep their current routes and commands: each resolves `get_or_create_default_search(session, user_id).id` and passes it on (`api/routers/{preferences,search,matches,jobs}.py`, `cli.py`, `scheduler.search_job`/`start_search` key their in-flight map by user as today but pass the default search id to `run_search`). `scheduler._match` loops over `select(Search.id)` instead of users and notes `search {id}: ...`. `digest._collect_pending` reads the latest search's preferences for `notify_email`/`min_score_to_notify` (Task 9 replaces this). Update every existing test to build its profile with `make_search`.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest && uv run mypy src && uv run ruff check .`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add -A src tests
git commit -m "refactor: key preferences, matches and search runs by a saved search"
```

---

### Task 2: A search scores only the jobs it fetched

**Files:**
- Modify: `src/jobscout/models/search.py`, `src/jobscout/models/__init__.py`, `src/jobscout/pipeline/ingest.py`, `src/jobscout/pipeline/searches.py`, `src/jobscout/pipeline/matching.py`, `src/jobscout/pipeline/search.py`
- Test: `tests/pipeline/test_ingest.py`, `tests/pipeline/test_searches.py`, `tests/pipeline/test_matching.py`, `tests/pipeline/test_search.py`, `tests/helpers.py`

**Interfaces:**
- Consumes: `Search`, `add_search`, `delete_search`, `select_candidates(session, prefs, search_id)` from Task 1.
- Produces:
  - `models.SearchJob` (table `search_job`; composite primary key `search_id` FK `search.id` + `job_id` FK `job.id`; `first_fetched_at: datetime` default utcnow).
  - `UpsertStats.seen_ids: list[int]` and `IngestResult.seen_ids: list[int]`: the id of every row a batch touched (created, updated, changed, and the existing twin a duplicate merged into), deduplicated, in order of first appearance.
  - `pipeline.searches.record_fetched(session, search_id: int, job_ids: list[int]) -> int` — inserts missing pairs, returns how many were new, commits; idempotent.
  - `select_candidates` additionally requires `Job.id IN (SELECT job_id FROM search_job WHERE search_id = :search_id)`.
  - `delete_search` also deletes the search's `SearchJob` rows.
  - `tests/helpers.py`: `fetched(session, search: Search, *jobs: Job) -> None` (wraps `record_fetched`); update existing matching tests that insert jobs directly to call it.

- [ ] **Step 1: Write the failing tests**

```python
# test_ingest.py
def test_seen_ids_cover_created_updated_and_merged_rows(session): ...
    # batch 1 creates A (source x); batch 2 re-sends A and sends B from source y with A's
    # fingerprint: result.seen_ids == [A.id] (B merged into A, no new row)

# test_searches.py
def test_record_fetched_is_idempotent(session):
    assert record_fetched(session, s.id, [j1, j2]) == 2
    assert record_fetched(session, s.id, [j2]) == 0

# test_matching.py
def test_a_search_only_scores_jobs_it_fetched(session): ...
    # job fetched by search A only: select_candidates for B is [], for A is [job]

# test_search.py
def test_a_search_records_every_job_it_fetched(session, respx_mock): ...
    # one posting answering two terms: one SearchJob row, result.fetched == distinct count
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/pipeline -k "seen_ids or record_fetched or only_scores or records_every" -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `run_search._fetch`, after each `ingest` outcome without error, call `record_fetched(session, search_id, outcome.seen_ids)` and accumulate the ids in a set; `result.fetched = len(ids)`. Delete `_CountedSource`, which `seen_ids` replaces.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat: record which search fetched which job, and score only those"
```

---

### Task 3: Store a city with its country, search and filter by it

**Files:**
- Modify: `src/jobscout/models/user.py`, `src/jobscout/sources/base.py`, `src/jobscout/sources/jobspy_base.py`, `src/jobscout/pipeline/search.py`, `src/jobscout/pipeline/filters.py`, `src/jobscout/matching/prompts.py`
- Test: `tests/pipeline/test_filters.py`, `tests/sources/test_scraped_sources.py`, `tests/pipeline/test_search.py`, `tests/matching/test_prompts.py`

**Interfaces:**
- Produces:
  - `UserPreferences.city: str | None = None` — meaningful only together with a country in `regions`.
  - `SearchQuery.city: str | None = None`.
  - `_queries_for` sets `city=prefs.city` on every query.
  - `JobSpySource.search_kwargs`: when a country was resolved and `query.city` is set, `location = f"{query.city}, {english_name(country)}"`. Indeed's override already drops `location` and keeps `country_indeed`; it needs no change.
  - `filters._names_no_city(location: str) -> bool`: true when every comma-separated part is empty, a country (`country_of`), an area name, or a work-mode word (`remote`, `remoto`, `hybrid`, `hibrido`, `on-site`, `onsite`, `presencial`, `anywhere`).
  - `_passes_region`, after the exclusion check, for a **non-remote** job when `prefs.city` is set: pass iff the folded location contains the folded city as a token sequence, **or** the location names one of the wanted countries and `_names_no_city(location)`, **or** the location is empty and `searched_region` vouches for a wanted country. Remote jobs keep today's country rule.
  - `profile_text` appends `City: <city>.` when set.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize(
    ("location", "remote", "searched", "expected"),
    [
        ("São Paulo, SP, Brazil", False, None, True),
        ("Sao Paulo - SP", False, None, True),
        ("Brazil", False, None, True),
        ("Remoto, Brasil", False, None, True),
        ("Rio de Janeiro, RJ, Brazil", False, None, False),
        ("Greater Curitiba", False, "Brazil", False),
        ("", False, "Brazil", True),
        ("United States", True, None, False),
        ("Brazil", True, None, True),
    ],
)
def test_city_rule(location, remote, searched, expected): ...
    # prefs: regions=["Brazil"], city="São Paulo"

def test_linkedin_searches_the_city_with_its_country(): ...  # kwargs["location"] == "Recife, Brazil"
def test_indeed_searches_the_country_when_a_city_is_set(): ...  # no "location", country_indeed == "Brazil"
def test_queries_carry_the_city(): ...  # every SearchQuery from _queries_for has city == "Recife"
def test_profile_text_names_the_city(): ...  # "City: Recife." in profile_text(prefs)
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/pipeline/test_filters.py tests/sources/test_scraped_sources.py tests/pipeline/test_search.py tests/matching/test_prompts.py -k "city" -v`
Expected: FAIL.

- [ ] **Step 3: Implement as listed under Interfaces**

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat: search and filter by a city stored with its country"
```

---

### Task 4: One reading of the paragraph, with suggested skills and no raise on empty terms

**Files:**
- Modify: `src/jobscout/matching/terms.py`
- Test: `tests/matching/test_terms.py`

**Interfaces:**
- Produces:
  - `MAX_SUGGESTED_SKILLS = 8`.
  - `_LLMOutput.suggested_skills: list[str]` (description: "Skills typical for the role the text describes, for the candidate to pick from."). `SYSTEM_PROMPT` gains: `- suggested_skills: up to 8 skills typical for this role, whether or not the text names them. They are options to choose from, not requirements.` The "use only what the text states" rule is reworded to apply to every field except `suggested_skills`.
  - `read_profile(paragraph: str, llm: BaseChatModel) -> ExtractedProfile` — raises `ValueError` only for an empty paragraph; returns `terms=[]` when none are usable. `suggested_skills` are deduplicated, exclude anything already in `required_skills` (case-insensitive), and are capped at `MAX_SUGGESTED_SKILLS`.
  - `extract_profile` becomes `read_profile` plus today's `ValueError` when `terms` is empty (behaviour unchanged for its callers).

- [ ] **Step 1: Write the failing tests**

```python
def test_read_profile_returns_empty_terms_instead_of_raising(): ...  # fake output terms=["a very long sentence here"] -> .terms == []
def test_suggested_skills_are_deduped_capped_and_exclude_required(): ...
    # required ["Python"], suggested ["python","RAG","rag", + 9 more] -> no "python", one "RAG", len <= 8
def test_extract_profile_still_raises_without_terms(): ...
def test_the_prompt_asks_for_suggested_skills(): ...  # "suggested_skills" in SYSTEM_PROMPT and in _LLMOutput fields
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/matching/test_terms.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement as listed under Interfaces**

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/matching`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/matching/terms.py tests/matching/test_terms.py
git commit -m "feat: read the paragraph with suggested skills and without raising on no terms"
```

---

### Task 5: The conversation, as pure logic

No database, no LLM. Everything the page shows during the conversation is computed here from a `Conversation`.

**Files:**
- Create: `src/jobscout/pipeline/conversation.py`, `tests/pipeline/test_conversation.py`

**Interfaces:**
- Consumes: `ExtractedProfile`, `profile_hash` (Task 4, `matching.terms`); `country_of`, `english_name` (`sources.regions`); `UserPreferences` (for `from_preferences`).
- Produces:
  ```python
  QuestionId = Literal["role", "level", "work_modes", "location", "country", "city", "skills"]
  QUESTION_NUMBER: dict[QuestionId, int]  # role 1, level 2, work_modes 3, location/country/city 4, skills 5
  JUNIOR_EXCLUSIONS = ("senior", "sr", "lead", "staff", "principal")

  class Answer(BaseModel):
      choice: str
      values: list[str] = []

  class Conversation(BaseModel):
      paragraph: str
      refinements: list[str] = []
      reading: ExtractedProfile | None = None
      reading_error: str | None = None
      answers: dict[QuestionId, Answer] = {}
      asked: list[QuestionId] = []      # order first shown, for the transcript
      confirmed: bool = False           # True after "Search jobs"; any change sets it False

  class Option(BaseModel):  choice: str; value: str | None = None
  class Question(BaseModel): id: QuestionId; number: int; position: int; total: int
                             multi: bool; typed: bool; options: list[Option]
  class Summary(BaseModel):  role: str | None; terms: list[str]; level: str | None
                             work_modes: list[str]; country: str | None; city: str | None
                             abroad_from: str | None; skills: list[str]
  class InvalidAnswerError(ValueError): ...
  class QuestionsPendingError(RuntimeError): ...
  ```
  Functions: `full_text(c) -> str` (paragraph and refinements joined by a blank line) · `with_reading(c, reading) -> Conversation` (clears `reading_error`, `confirmed=False`) · `with_reading_error(c, message) -> Conversation` · `with_refinement(c, text) -> Conversation` · `pending(c) -> list[QuestionId]` · `current_question(c) -> Question | None` · `answer(c, qid, a: Answer) -> Conversation` (validates, appends `qid` to `asked` if new, `confirmed=False`) · `summary(c) -> Summary` · `to_preferences(c) -> dict[str, object]` (raises `QuestionsPendingError` when `pending(c)`) · `widenings(c) -> list[tuple[str, QuestionId, Answer]]` · `title(c) -> str` · `from_preferences(prefs: UserPreferences) -> Conversation`.

**Rules the tests pin** (the "effective" value of a field is the answer when there is one, else what the reading states):

| Question | Pending when | Options (single unless noted) | Valid answers |
|---|---|---|---|
| role | no reading, or reading has no terms (then nothing else is pending) | none, `typed=True` | not answerable; typed text arrives as a refinement |
| level | no answer and `reading.seniority` empty | `intern, junior, mid, senior, any` | `choice` in those |
| work_modes | no answer and `reading.stated_work_modes` empty | `remote, hybrid, onsite, any` (multi) | `choice="pick"` with values ⊆ {remote, hybrid, onsite}, non-empty; or `choice="any"` |
| location | effective modes == {remote}, no `location` answer, and no stated region resolves to a country | `country`+home (if home known), `anywhere`, `abroad`+home (if home known), `other` (typed) | `country` with one value that `country_of` resolves (stored as `english_name`), `anywhere`, `abroad` (only when a home country is known) |
| country | effective modes not remote-only (empty = any counts as not remote-only), no country known, no `country` answer | `anywhere`, `other` (typed) | `country` (resolved as above) or `anywhere` |
| city | not remote-only, a country is known, no `city` answer, no stated region that names no country | `anywhere` (value = the country), `other` (typed) | `city` with one non-empty value, or `anywhere` |
| skills | no answer, `reading.required_skills` empty, `reading.suggested_skills` non-empty | one `skill` option per suggestion (multi) | `choice="pick"`, any values (empty allowed) |

- Home country = the `location`/`country` answer when its choice is `country`, else the first stated region that resolves to a country.
- Answering `location` or `country` with a different country drops the `city` answer.
- `position`/`total` count question **numbers** (country and city share 4): `total` = distinct numbers in `asked` plus distinct numbers still pending; `position` = the current question's number's index in that sequence, 1-based.
- `to_preferences`: `profile_summary=full_text`, `profile_hash=profile_hash(full_text)`, `search_terms=reading.terms`; `seniority` = `[level]` (`any` → `[]`) else `reading.seniority`; `excluded_keywords` = `reading.excluded_keywords` + `JUNIOR_EXCLUSIONS` when level is intern/junior, deduplicated; `work_modes` = effective (`any` → `[]`); remote-only: `country` → `regions=[c]`, `anywhere` → `[]`, `abroad` → `regions=[]`, `excluded_regions=[home]`, unanswered → stated countries; otherwise `regions=[country]` or `[]` for `anywhere`, `city` from the answer or the stated city, `None` when remote-only or no country; `required_skills` = skills answer values else `reading.required_skills`.
- `widenings`, each only when it changes something: `("include_remote", "work_modes", ...)` when modes are non-empty without remote; `("include_hybrid", ...)` likewise for hybrid; `("whole_country", "city", Answer(choice="anywhere"))` when a city is set; `("any_level", "level", Answer(choice="any"))` when seniority is non-empty.
- `title`: level (effective, omitted for `any`/none) + first term, words capitalised, with `ai, ml, llm, qa, ui, ux, bi, sre, nlp` upper-cased ("Junior AI Engineer"); with no terms, the first six words of the paragraph cut to 60 characters.
- `from_preferences`: paragraph = `profile_summary`, `reading` = an `ExtractedProfile` with `terms=search_terms`, answers rebuilt from the stored seniority, work modes, regions/excluded regions/city and required skills, `confirmed=True`.

- [ ] **Step 1: Write the failing tests**

One test per rule, named for the behaviour. At minimum:
```python
def test_no_terms_asks_only_for_the_role(): ...
def test_a_paragraph_that_states_everything_asks_nothing(): ...
def test_questions_come_in_order_with_a_counter(): ...  # level first: position 1, total 4
def test_remote_only_asks_where_you_can_work_from(): ...  # options include abroad when home known
def test_hybrid_asks_the_country_then_the_city(): ...
def test_dont_mind_on_work_mode_still_asks_the_city(): ...
def test_a_clicked_answer_beats_a_new_reading(): ...  # answered remote; new reading states hybrid -> summary still remote
def test_a_reading_that_adds_hybrid_asks_for_the_city(): ...  # Review Focus 2
def test_changing_the_country_drops_the_city(): ...
def test_unknown_country_is_rejected(): ...  # InvalidAnswerError
def test_abroad_without_a_home_country_is_rejected(): ...
def test_junior_excludes_senior_titles(): ...
def test_abroad_stores_home_as_excluded(): ...  # regions == [], excluded_regions == ["Brazil"]
def test_city_is_stored_with_its_country(): ...  # regions == ["Brazil"], city == "Recife"
def test_to_preferences_refuses_while_questions_are_pending(): ...
def test_widenings_offer_only_what_changes_something(): ...
def test_title_reads_level_and_role(): ...  # "Junior AI Engineer"
def test_title_falls_back_to_the_paragraph(): ...
def test_from_preferences_round_trips_through_to_preferences(): ...
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/pipeline/test_conversation.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `pipeline/conversation.py` per the table and rules above**

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/pipeline/test_conversation.py -v && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jobscout/pipeline/conversation.py tests/pipeline/test_conversation.py
git commit -m "feat: the search conversation as pure, deterministic logic"
```

---

### Task 6: Persist the conversation, confirm it, and run on confirmed preferences

**Files:**
- Modify: `src/jobscout/matching/llm.py`, `src/jobscout/pipeline/searches.py`, `src/jobscout/pipeline/search.py`
- Test: `tests/matching/test_llm.py`, `tests/pipeline/test_searches.py`, `tests/pipeline/test_search.py`

**Interfaces:**
- Consumes: Task 5's module; `read_profile` (Task 4); `record_fetched` (Task 2); `save_preferences(session, settings, search_id, changes)` (Task 1).
- Produces:
  - `matching.llm.provider_key_found(settings) -> bool` — true when the provider is known and needs no key or has one. Imports nothing.
  - `pipeline.searches`:
    - `conversation_of(search: Search) -> Conversation` and `save_conversation(session, search, conversation) -> Search` (writes JSON via `model_dump(mode="json")`, refreshes `title`, `touch`es).
    - `create_search(session, settings, user_id, paragraph: str, chat: BaseChatModel) -> Search` — raises `MissingProviderError` before writing anything when `provider_key_found` is false and `ValueError` for a blank paragraph; otherwise `add_search`, then one reading.
    - `answer_question(session, user_id, search_id, question: QuestionId, answer: Answer) -> Search`.
    - `refine(session, user_id, search_id, text: str, chat) -> Search` (appends, reads again; never runs).
    - `reread(session, user_id, search_id, chat) -> Search` ("Try again").
    - `confirm(session, settings, user_id, search_id) -> UserPreferences` — `to_preferences`, then `save_preferences` (stales this search's matches when relevant fields change), sets `confirmed=True`.
    - A reading failure of any exception type becomes `with_reading_error(c, f"{type(exc).__name__}: {exc}")`; the search is kept.
  - `pipeline.search.run_search(session, settings, search_id, deps=None, run_id=None, on_progress=None, fetch: bool = True) -> SearchResult` — terms are `prefs.search_terms`; no extraction call. Empty terms fail the run with `"the search has no confirmed terms: answer its questions and press Search jobs"`. `fetch=False` ("Rank the rest") skips sources and scores what is pending; its `ok` is "did not error with nothing evaluated". `_resolve_terms` and `_EXTRACTED_PREFERENCES` are deleted.

- [ ] **Step 1: Write the failing tests**

```python
# test_llm.py
def test_provider_key_found(): ...  # google without key False, with key True, ollama True, unknown False

# test_searches.py  (chat = CountingChatModel(results=[_LLMOutput(...)]) from tests/matching/fakes.py)
def test_create_search_reads_the_paragraph_once_and_titles_it(session): ...  # chat.calls == 1; title "Junior AI Engineer"
def test_create_search_writes_no_preferences(session): ...  # prefs.search_terms == [] until confirm
def test_create_search_without_a_key_writes_nothing(session): ...  # MissingProviderError; no Search rows
def test_a_failed_reading_keeps_the_search_and_its_paragraph(session): ...  # Review Focus 3
def test_reread_clears_the_error(session): ...
def test_refine_keeps_answers_and_reads_the_whole_text(session): ...  # chat sees paragraph + refinement
def test_confirm_writes_the_summary_as_preferences(session): ...
def test_confirm_refuses_with_questions_pending(session): ...  # QuestionsPendingError
def test_confirm_stales_only_this_searchs_matches(session): ...

# test_search.py
def test_run_search_uses_confirmed_terms_and_reads_nothing(session, respx_mock): ...
    # chat.schemas contains no _LLMOutput; queries use prefs.search_terms
def test_run_search_without_confirmed_terms_fails_the_run(session): ...
def test_ranking_scores_pending_jobs_without_fetching(session): ...  # fake source .fetch never called
```
Delete the `test_search.py` tests that pin `_resolve_terms` (stored terms reused by `profile_hash`, a run writing `search_terms`/`seniority`/`required_skills`/`excluded_keywords`, "an extraction that finds nothing does not erase…"); confirm now owns that behaviour.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/matching/test_llm.py tests/pipeline/test_searches.py tests/pipeline/test_search.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement as listed under Interfaces**

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat: persist the conversation and run searches on confirmed preferences"
```

---

### Task 7: Upgrade an existing database to saved searches

**Files:**
- Create: `src/jobscout/pipeline/upgrade.py`, `tests/pipeline/test_upgrade.py`
- Modify: `src/jobscout/db.py`, `src/jobscout/cli.py`, `src/jobscout/api/app.py`, `README.md` ("Upgrading an existing database")
- Test: `tests/test_db.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `tests/fixtures/schema_pre_searches.sql` (Task 1); `from_preferences`, `title` (Task 5); `Search`, `SearchJob`.
- Produces:
  - `db.DatabaseNeedsUpgradeError(RuntimeError)`; `db.needs_upgrade(engine) -> bool` (table `user_preferences` exists without a `search_id` column); `init_db` raises `DatabaseNeedsUpgradeError("This database predates saved searches. Back it up and run `jobscout upgrade-db`.")` when it does, before `create_all`.
  - `pipeline.upgrade.UpgradeReport(searches: int, matches: int, runs: int)` dataclass.
  - `pipeline.upgrade.backup_sqlite(url: str, now: datetime) -> Path | None` — copies the file to `<file>.bak-YYYYMMDD-HHMMSS`; `None` for in-memory or non-SQLite URLs.
  - `pipeline.upgrade.upgrade_database(engine) -> UpgradeReport` — no-op report of zeros when `needs_upgrade` is false. In **one transaction**: read the old `user_preferences` and `match` rows through reflected tables (JSON columns come back decoded), drop both tables, `SQLModel.metadata.create_all(conn)`, add `run.search_id` with its index if missing; per old preferences row insert a `Search` (`conversation=from_preferences(...)`, `title=title(conv)` or `"My search"` when there are no terms) and its preferences with `search_id`; copy matches keeping their `id`, `status`, `notified_at`, with the user's `search_id`; insert a `SearchJob` per matched job; set `run.search_id` for that user's `job='search'` runs. Any failure rolls everything back.
  - CLI `jobscout upgrade-db`: builds the engine **without** `init_db`, prints the backup path, runs `upgrade_database`, prints `searches=N matches=N runs=N`, or `Already up to date.`. Other commands catch `DatabaseNeedsUpgradeError` in `_session()` and exit 2 with its message. The API lifespan logs the message at error level and re-raises.

- [ ] **Step 1: Write the failing tests**

Fixture `old_db(tmp_path)`: a file SQLite built from `schema_pre_searches.sql`, with one user, preferences (paragraph, `search_terms=["ai engineer"]`, `seniority=["junior"]`, `work_modes=["remote"]`, `regions=["Brazil"]`), two jobs, two matches (one `applied`, one `new` with score 80 and `notified_at` set), one `search` run for the user.
```python
def test_needs_upgrade_detects_the_old_shape(old_db): ...  # True; False on a fresh init_db engine
def test_init_db_refuses_an_old_database(old_db): ...  # pytest.raises(DatabaseNeedsUpgradeError, match="upgrade-db")
def test_upgrade_turns_preferences_into_a_first_search(old_db): ...
    # one Search; title "Junior AI Engineer"; prefs copied; conversation confirmed;
    # summary(conv).work_modes == ["remote"], .country == "Brazil"
def test_upgrade_keeps_matches_with_their_status_and_ids(old_db): ...
def test_upgrade_scopes_matched_jobs_to_the_search(old_db): ...  # two SearchJob rows
def test_upgrade_links_search_runs(old_db): ...
def test_upgrade_is_a_no_op_on_a_current_database(engine): ...
def test_upgrade_rolls_back_when_it_fails(old_db, monkeypatch): ...
    # monkeypatch from_preferences to raise; old user_preferences and match still readable
def test_backup_copies_the_sqlite_file(tmp_path): ...  # and returns None for "sqlite://"
# test_cli.py
def test_upgrade_db_command_backs_up_and_upgrades(old_db, monkeypatch): ...
def test_commands_on_an_old_database_say_to_upgrade(old_db, monkeypatch): ...  # exit 2, message
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/pipeline/test_upgrade.py tests/test_db.py tests/test_cli.py -k "upgrade or old" -v`
Expected: FAIL.

- [ ] **Step 3: Implement as listed under Interfaces**

README: replace nothing above; add a dated subsection saying that this version reorganises preferences into saved searches, that the `ALTER TABLE` lines do not cover it, and that `jobscout upgrade-db` backs up the SQLite file and converts it. State that Postgres is not supported by the upgrade (no released install uses it).

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run mypy src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A src tests README.md
git commit -m "feat: upgrade an existing database to saved searches"
```

---

### Task 8: One search at a time, and scheduled matching per search

**Files:**
- Modify: `src/jobscout/scheduler.py`, `src/jobscout/api/routers/search.py` (call-site only)
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `run_search(..., fetch=...)` (Task 6), `open_search_run(session, search_id)` (Task 1).
- Produces:
  - `class SearchBusyError(RuntimeError)` with attribute `search_id: int` (the running one).
  - `JobScoutScheduler.start_search(search_id: int, fetch: bool = True) -> int` — returns the in-flight run id when this search is already running (whatever `fetch`), raises `SearchBusyError` when another search is running, otherwise opens a run and schedules it. The per-user `_searches` dict becomes one `_running: tuple[int, int] | None` (search id, run id) under `_search_lock`.
  - `JobScoutScheduler.running_search() -> tuple[int, int] | None`.
  - `search_job(engine, settings, search_id: int, run_id: int, fetch: bool = True) -> None`.
  - `_match` loops over every `Search` id; a `run_match` `error` becomes the note `search {id}: {error}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_second_start_of_the_same_search_returns_its_run(): ...
def test_starting_another_search_while_one_runs_is_refused(): ...  # SearchBusyError, .search_id == first
def test_ranking_starts_a_run_without_fetching(): ...  # search_job called with fetch=False
def test_the_slot_frees_after_the_search_finishes(): ...  # running_search() is None afterwards; a new start works
def test_the_slot_frees_when_scheduling_fails(): ...
def test_match_job_scores_every_search(): ...  # two searches, each with its own fetched job: two matches
```
Adapt the existing per-user search tests in `tests/test_scheduler.py` to the new signature.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/test_scheduler.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement as listed under Interfaces**

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat: run one search at a time per instance, and match every search on schedule"
```

---

### Task 9: Listings across searches: waiting count, My jobs, verdicts, digest

**Files:**
- Modify: `src/jobscout/pipeline/run.py`, `src/jobscout/pipeline/digest.py`, `src/jobscout/scheduler.py` (`_collect_pending`)
- Test: `tests/pipeline/test_run.py`, `tests/pipeline/test_digest.py`, `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `select_candidates` (Task 2), `list_matches(session, search_id, ...)` (Task 1).
- Produces:
  - `count_waiting(session, search_id) -> int` — `len(select_candidates(...))` for that search.
  - `MyJobTab = Literal["all", "saved", "applied"]`; `@dataclass MyJob(match: Match, job: Job, searches: list[tuple[int, str]])`; `@dataclass MyJobs(items: list[MyJob], counts: dict[MyJobTab, int])`.
  - `list_my_jobs(session, user_id, tab: MyJobTab = "all", search_id: int | None = None, limit: int = 200) -> MyJobs` — one item per active job, the user's best-scored match for it (ties: newest), naming every search that scored it; `all` = scored and not `dismissed`; `saved`/`applied` = that status; `counts` covers all three tabs under the same `search_id` filter; ordered by score desc.
  - `set_match_status` applies the verdict to **every** match the user has for that job (a verdict is about the job), returns the requested row.
  - `digest.select_unnotified(session, user_id, min_score, limit)` merges across searches: one row per job, best score; `held_back` counts jobs.
  - `digest.mark_notified(session, user_id: int, job_ids: list[int], now=None)` marks every match of those jobs for that user.
  - `digest.digest_target(session, user_id) -> tuple[str, int] | None` — `(notify_email, min_score_to_notify)` from the user's most recently used search that has `notify_email` set.

- [ ] **Step 1: Write the failing tests**

```python
def test_count_waiting_counts_only_this_searchs_pending_jobs(session): ...
def test_my_jobs_shows_a_job_found_twice_once_at_its_best_score(session): ...
    # scores 60 (search A) and 85 (search B): one item, score 85, searches == [(A, ...), (B, ...)]
def test_my_jobs_tabs_and_counts(session): ...  # saved/applied/dismissed fixture; counts == {"all": 3, "saved": 1, "applied": 1}
def test_my_jobs_filters_by_search(session): ...
def test_a_verdict_applies_to_every_search_that_found_the_job(session): ...
def test_digest_sends_a_job_found_twice_once(session): ...
def test_marking_notified_covers_every_search(session): ...
def test_digest_target_uses_the_latest_search_with_an_address(session): ...
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/pipeline/test_run.py tests/pipeline/test_digest.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement as listed under Interfaces; switch `_collect_pending` to `digest_target` and the new `mark_notified`**

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat: list jobs across searches and merge them in verdicts and the digest"
```

---

### Task 10: The API the page needs

**Files:**
- Create: `src/jobscout/api/routers/searches.py`, `src/jobscout/api/routers/my_jobs.py`, `src/jobscout/api/routers/status.py`, `tests/api/test_searches.py`, `tests/api/test_my_jobs.py`, `tests/api/test_status.py`
- Modify: `src/jobscout/api/{app,deps,schemas}.py`, `src/jobscout/api/routers/{matches,jobs}.py`, `src/jobscout/pipeline/users.py`
- Delete: `src/jobscout/api/routers/{preferences,search}.py`, `tests/api/test_preferences.py`, `tests/api/test_search.py` (their cases move to `test_searches.py`)

**Interfaces:**
- Consumes: Tasks 5, 6, 8, 9.
- Produces:
  - `deps.get_chat_model() -> BaseChatModel` (`chat_model(get_settings())`; tests override it with a fake).
  - App exception handlers: `MissingProviderError` → 409 `{"detail": str, "code": "no_llm_key"}`; `SearchNotFoundError` → 404; `SearchBusyError` → 409 `{"detail": "Another search is running", "code": "search_busy", "search_id": n}`; `QuestionsPendingError` → 409 `code: "questions_pending"`; `InvalidAnswerError` → 422.
  - `pipeline.users.set_locale(session, user_id, locale: str) -> User` (`"en"` or `"pt-BR"`, else `ValueError`).
  - Routes (all scoped to the current user):

| Method, path | Body / query | Response |
|---|---|---|
| `GET /searches` | | `list[SearchListItem(id, title, last_used_at, running: bool)]` |
| `POST /searches` | `{paragraph}` | 201 `SearchRead` |
| `GET /searches/{id}` | | `SearchRead` |
| `DELETE /searches/{id}` | | 204; 409 `search_busy` when it is the running one |
| `POST /searches/{id}/answers` | `{question, choice, values}` | `SearchRead` |
| `POST /searches/{id}/refinements` | `{text}` | `SearchRead` |
| `POST /searches/{id}/reread` | | `SearchRead` |
| `POST /searches/{id}/run` | | 202 `{run_id}` (confirm, then `start_search(id)`) |
| `POST /searches/{id}/rank` | | 202 `{run_id}` (`start_search(id, fetch=False)`) |
| `GET /searches/{id}/runs/{run_id}` | | `RunRead` (404 unless the run belongs to the search) |
| `GET /searches/{id}/matches` | `status`, `min_score`, `limit` | `{matches: list[MatchRead], found: int, waiting: int}` (`found` = default listing length, `waiting` = `count_waiting`) |
| `PATCH /matches/{match_id}` | `{status}` | `MatchRead` (kept; now propagates per Task 9) |
| `GET /my-jobs` | `tab`, `search_id` | `{items: list[MyJobRead(match: MatchRead, searches: list[{id, title}])], counts}` |
| `GET /jobs` | `search_id` (default latest; none → every active job unfiltered), `limit`, `all` | `list[JobRead]` |
| `GET /status` | | `{llm_key_found, llm_provider, llm_model, embedding_model, sources: list[SourceStatus], running_search_id, locale}` |
| `PUT /me/locale` | `{locale}` | `{locale}` |

  - `SearchRead`: `id, title, created_at, last_used_at, paragraph, refinements, reading: ReadingRead | None (terms, seniority, required_skills, stated_work_modes, stated_regions, suggested_skills), reading_error, asked, answers: dict[str, Answer], question: Question | None, summary: Summary, confirmed, widenings: list[{id, question, answer}], latest_run: RunRead | None`. `RunRead` gains `search_id`. `GET /matches` (unscoped) is removed.
  - `GET /sources` and `GET /runs` are unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_create_search_returns_the_first_question(client): ...  # 201, question.id == "level", position 1
def test_create_search_without_a_key_is_refused(client, monkeypatch): ...  # 409 code no_llm_key, GET /searches == []
def test_answering_moves_to_the_next_question(client): ...
def test_an_invalid_answer_is_422(client): ...
def test_refining_returns_the_summary_without_running(client): ...  # no run in GET /runs
def test_run_refuses_with_questions_pending(client): ...  # 409 questions_pending
def test_run_starts_and_reports_progress(client, fake_scheduler): ...  # 202 run_id; GET runs/{run_id} 200
def test_starting_a_second_search_is_409(client, fake_scheduler): ...  # code search_busy
def test_deleting_the_running_search_is_refused(client, fake_scheduler): ...  # Review Focus 4
def test_matches_report_found_and_waiting(client): ...
def test_another_users_search_is_404(client): ...
def test_my_jobs_lists_across_searches(client): ...
def test_status_reports_the_key_without_revealing_it(client, monkeypatch): ...  # body has no key value
def test_locale_is_saved(client): ...  # "pt-BR" ok; "fr" 422
```
A fixture sets `GOOGLE_API_KEY=test` with `monkeypatch` and overrides `get_chat_model` with a `CountingChatModel`; the no-key test deletes the variable. `fake_scheduler`: a stub on `app.state.scheduler` with `start_search` and `running_search`, following how `tests/api/test_search.py` stubs it today.

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/api -v`
Expected: FAIL.

- [ ] **Step 3: Implement the routers, schemas, handlers and deletions**

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest && uv run mypy src && uv run ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "feat: per-search API for the conversation, runs, results and My jobs"
```

---

### Task 11: CLI follows the latest search; docs

**Files:**
- Modify: `src/jobscout/cli.py`, `README.md` (API and CLI sections), `CLAUDE.md` ("Current state", "Commands")
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `latest_search`, `list_searches`, `get_search` (Task 1), `run_search` (Task 6).
- Produces:
  - `jobscout searches` — one line per search: `id`, title, last used, newest first; `No searches yet. Start one in the page: jobscout serve` when none.
  - `--search ID` option on `search`, `match`, `matches`, `jobs`; default `latest_search`. With no searches: `search` and `match` print the "No searches yet…" line and exit 2; `matches` prints it and exits 0; `jobs` lists every active job unfiltered.
  - `get_or_create_default_search` has no caller left and is deleted with its test.

- [ ] **Step 1: Write the failing tests**

```python
def test_searches_lists_newest_first(...): ...
def test_search_defaults_to_the_latest_search(...): ...  # run_search called with the latest id
def test_search_takes_an_explicit_search(...): ...
def test_search_with_no_searches_says_how_to_start(...): ...  # exit 2, "jobscout serve" in output
def test_matches_with_no_searches_exits_cleanly(...): ...
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement; update README (routes table, `upgrade-db`, `searches`) and CLAUDE.md (current state: saved searches backend done, page next; commands list)**

- [ ] **Step 4: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add -A src tests README.md CLAUDE.md
git commit -m "feat: CLI follows the latest search; document saved searches"
```

# The Conversational Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build JobScout's face: a static HTML/CSS/JS page served by FastAPI that implements the twelve screens of the conversational interface over the per-search API that is already merged.

**Architecture:** Four small backend additions the page needs (per-source run progress, off sources, a question by id, a job's work mode), then the page under `src/jobscout/web/`: one `index.html`, one stylesheet over the design system's tokens and `js-*` components, and native ES modules with no build step. Rendering goes through one `h()` helper that only ever creates text nodes for data. Pure logic (formatting, the transcript, the run's view state, i18n) lives in modules tested with Node's built-in `node --test`; the page as a whole is verified by running it against seeded demo data and comparing each screen with its PNG.

**Tech Stack:** Python 3.12, FastAPI `StaticFiles`, SQLModel; plain JavaScript (ES2022 modules), CSS custom properties; `node --test` (Node ≥ 20, no npm packages).

**Spec:** `docs/superpowers/specs/2026-11-07-chat-interface-design.md` (screens in `docs/superpowers/specs/assets/2026-11-07-chat-interface/`). Earlier page decisions that still stand: `docs/superpowers/specs/2026-10-22-stage-5-sources-and-dashboard-design.md` §2 and §5.2–5.3 (polling every 2 s, cards reorder as scores arrive, English and pt-BR with English default, the design system shipped inside the package). Design system: `jobscout-design/DESIGN.md` (moves to `src/jobscout/web/design/` in Task 2).

## Global Constraints

- No frontend build step, no framework, no npm dependency. Static files served by FastAPI; scripts are `<script type="module">`. External resources: Google Fonts only, as `DESIGN.md` prescribes.
- Colours, type, spacing and radii come only from `design/tokens.css` (`var(--…)`) and the `js-*` classes in `design/components.css`. No raw hex, px font sizes or off-scale spacing in `app.css`; new layout values use the `--space-*` scale.
- Dark theme by default; `data-theme` on `<html>`; the theme lives in `localStorage` (`jobscout.theme`), set before first paint. The language lives in `User.locale` (`PUT /me/locale`); default English. Both themes and both locales must render every screen.
- **Language:** the spec overrides `DESIGN.md`'s "pt-BR only": UI copy exists in `en` and `pt-BR`, sentence case, no emoji. English copy is the mockups' text (see the copy table below); pt-BR is written to the same tone.
- **No LLM-written chat text.** Every sentence the page shows is a fixed i18n string with placeholders filled from API data. Explanations (`reasoning`) are shown as written, in whatever language they were written in.
- **Data is never markup.** Page code never assigns data to `innerHTML`/`outerHTML`/`insertAdjacentHTML`; the only `innerHTML` allowed is the static SVG strings in `icons.js`. A job's URL becomes a link only when it is `http:` or `https:`; links to postings open with `target="_blank" rel="noopener noreferrer"`.
- **Orange points, it does not decorate:** at most one primary button per screen; the score tag uses `js-tag--match`; status always carries a word or icon, never colour alone; no orange in the running screen (`05`) — progress uses `--info`.
- Layout: sidebar 260 px; main column 720 px for the conversation and 1000 px once results appear; composer pinned at the bottom of the main column; detail panel on the right (`07`). Below 800 px: one column, the sidebar behind a menu button, the detail panel full-screen.
- Polling: every 2 s while a run is in flight, never otherwise.
- Operator config is never edited from the page; no field ever accepts or shows an API key.
- Python gate before every commit: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest`. JS gate (from Task 3): `node --test tests/web/`. CI runs both.
- English for code, comments, docs.

**Copy (English, from the mockups; i18n keys are the implementer's):** `New search` · `Searches` · `Your searches appear here` · `My jobs` · `Settings` · `What job are you looking for?` · placeholder `e.g. I'm a Python developer with 1 year of experience and LLM projects. I'm looking for a junior AI Engineer role, ideally at a company working on AI products.` · `Start search` · `Add an LLM key to start searching.` / `Set LLM_PROVIDER and its API key in the .env file, then restart jobscout.` / `How to set it up` · `Got it: {what}. A few quick questions.` (without the second sentence when nothing is asked) · `{n} of {total}` · `What role are you looking for?` · `Which level are you aiming for?` (`Intern`, `Junior`, `Mid-level`, `Senior`, `Don't mind`) · `How do you want to work? Pick all that fit.` (`Remote`, `Hybrid`, `On-site`, `Don't mind`) · `Where can you work from?` (`{country}`, `Anywhere`, `Abroad, not {country}`, `Other country`) · `Which country?` (`Anywhere`, `Other country`) · `Where in {country}?` (`Anywhere in {country}`, `Other city`) · `Which skills should count most?` · `Continue` · `Choose an option above to continue` · `Type an answer or add a detail` · `Add a detail to refine this search` · `Send` · `Here's what I'll search for.` · rows `Role`, `Level`, `Work mode`, `Location`, `Skills` · `{n} sources: {names}` · `Search jobs` · `Searching…` · `Searching {n} sources.` · `done · {n} jobs` · `searching · term {i} of {n}` · `waiting` · `Scoring {done} of {total} jobs` · `Found {n} jobs that fit.` + ` {m} more are waiting for a score.` · `Rank the rest` · `Search again` · `No jobs matched. I searched {n} sources and found {m} postings, but none fit {what}.` · `Try widening the search:` (`Include remote jobs`, `Include hybrid jobs`, `Search all of {country}`, `Any level`) · `{source} did not answer ({detail}). The other sources still ran.` · `Fit score` · `Matches` · `Missing` · `Watch out` · `Open posting` · `Save` · `Saved` · `Mark as applied` · `Dismiss` · `All` · `Saved` · `Applied` · `All searches` · `No saved jobs yet.` / `Save a job from a search's results and it appears here.` · `Model`, `Provider`, `Chat model`, `Embeddings`, `Status`, `Key found` / `No key found`, `Change these in .env and restart jobscout.` · `Sources`, `Active`, `Off`, `Turn sources on or off with SOURCES in .env.` · `Appearance`, `Theme`, `Dark`, `Light`, `Language`, `English`, `Português` · `Another search is running.` · `Try again` · `Delete` / `Delete this search?` / `Cancel`.

## Review Focus

1. **Markup in scraped or provider text** (a job title `<img onerror=…>`, a `reasoning` or `reading_error` with tags): it must appear as literal text. Pinned in Task 3 (`h()` node test) and Task 3's pytest guard against `innerHTML` outside `icons.js`.
2. **A posting URL that is not http(s)** (`javascript:alert(1)`): no link is rendered, the text still shows. Pinned in Task 7 (`safeUrl` node test).
3. **A run left unfinished by a restart** (latest run has no `finished_at` but `/status.running_search_id` is not this search): the page shows it as interrupted with "Search again", and does not poll forever. Pinned in Task 7 (`runView` node test).
4. **Another search already running** (409 `search_busy` on "Search jobs" or "Rank the rest", or on delete): the page shows "Another search is running." with a link to that search, and nothing else changes. Pinned in Task 4 (`apiError` node test) and checked in Task 9.
5. **Switching language** with a mixed screen: every key exists in both locales with the same placeholders, and switching never re-requests explanations. Pinned in Task 3 (`test_locales_have_the_same_keys_and_placeholders`).

---

### Task 1: Per-source progress and live scoring counts on the run

The running screen (`05`) shows one line per source ("searching · term 2 of 3") and "Scoring 12 of 40 jobs". Today a `Run` only holds totals, and scoring progress is reported to a callback but never written.

**Files:**
- Modify: `src/jobscout/models/run.py`, `src/jobscout/pipeline/search.py`, `src/jobscout/api/schemas.py`, `src/jobscout/db.py` (`needs_upgrade`), `src/jobscout/pipeline/upgrade.py`, `README.md` (upgrade subsection: one line)
- Test: `tests/pipeline/test_search.py`, `tests/pipeline/test_upgrade.py`, `tests/test_db.py`, `tests/api/test_searches.py`

**Interfaces:**
- Produces:
  - `Run.sources: list[dict[str, object]]` (JSON, not null, default `[]`). One entry per source the run will use, in run order: `{"name": str, "state": "waiting"|"searching"|"done"|"failed"|"skipped", "fetched": int, "queries_done": int, "queries_total": int, "detail": str | None}`. `detail` is the error text for `failed`, the reason for `skipped`, else `None`.
  - Counters gain `"scored"` and `"to_score"`: `to_score` is set when scoring starts (the number selected for evaluation), `scored` advances and is published after every evaluated job. A `fetch=False` run has an empty `sources` list.
  - `run_search` writes the whole `sources` list as `waiting` before the first fetch, flips each to `searching` with `queries_total` when its turn comes, updates `queries_done`/`fetched` after each query, and sets `done`/`failed`/`skipped` at the end of that source (the existing `all_remote` skip → `skipped` with its reason). Assign a new list each time (a mutated JSON value is not marked dirty).
  - `RunRead.sources: list[RunSource]` with `RunSource(name, state, fetched, queries_done, queries_total, detail)`.
  - `db.needs_upgrade` is also true when table `run` lacks a `sources` column; `upgrade_database` adds it (`ALTER TABLE run ADD COLUMN sources JSON NOT NULL DEFAULT '[]'`) whether or not the searches conversion is needed, inside the same transaction.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_search_run_records_each_sources_progress(session, respx_mock): ...
    # two sources, second fails on its first term: run.sources ==
    # [{"name": "himalayas", "state": "done", "fetched": N, "queries_done": 2, "queries_total": 2, "detail": None},
    #  {"name": "remotive", "state": "failed", "fetched": 0, "queries_done": 0, "queries_total": 2, "detail": "<error text>"}]
def test_sources_are_published_while_the_run_is_going(session): ...
    # a fake source whose fetch reads the Run row from a second session: it sees itself as "searching"
def test_a_remote_only_board_is_recorded_as_skipped(session): ...
def test_scoring_progress_is_published_after_each_job(session): ...
    # on_progress hook reads counters from a second session at each "evaluated" step: scored == done
def test_ranking_runs_have_no_sources(session): ...
def test_needs_upgrade_when_run_has_no_sources_column(tmp_path): ...
def test_upgrade_adds_the_sources_column_to_an_upgraded_database(tmp_path): ...
def test_run_read_includes_sources(client, ...): ...  # GET /searches/{id}/runs/{run_id}
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/pipeline/test_search.py tests/pipeline/test_upgrade.py tests/test_db.py tests/api/test_searches.py -k "sources or scoring_progress" -v`
Expected: FAIL.

- [ ] **Step 3: Implement as listed under Interfaces**

- [ ] **Step 4: Run the full Python gate**

Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: record each source's progress and live scoring counts on a search run"
```

---

### Task 2: What else the page needs from the server, and serving it

**Files:**
- Move: `jobscout-design/` → `src/jobscout/web/design/` (keep `DESIGN.md`, `tokens.css`, `tokens.json`, `components.css`, `logos/`, `examples/`; drop `tailwind.preset.js`, `README.md` and `CLAUDE.md`, whose instructions move to the repo `CLAUDE.md`)
- Create: `src/jobscout/web/index.html` (a minimal shell for now: head with fonts, `design/tokens.css`, `design/components.css`, `app.css`, the theme bootstrap, and `<script type="module" src="/static/app.js">`), `src/jobscout/web/app.css` (empty but for a comment), `src/jobscout/web/app.js` (renders nothing yet), `tests/api/test_web.py`
- Modify: `src/jobscout/api/app.py`, `src/jobscout/api/routers/searches.py`, `src/jobscout/api/routers/status.py`, `src/jobscout/api/schemas.py`, `src/jobscout/pipeline/filters.py`, `src/jobscout/sources/registry.py`, `CLAUDE.md` (a short "UI" section: read `src/jobscout/web/design/DESIGN.md` before UI work; tokens only; both themes; the spec's English+pt-BR rule overrides its pt-BR-only line)
- Test: `tests/api/test_searches.py`, `tests/api/test_status.py`, `tests/pipeline/test_filters.py`, `tests/sources/test_registry.py`

**Interfaces:**
- Produces:
  - `GET /` → `index.html` (`text/html`, `Cache-Control: no-cache`); `app.mount("/static", StaticFiles(directory=<package web dir>), name="static")`, so `/static/design/tokens.css`, `/static/app.js`, `/static/locales/en.json` resolve. The directory is located with `importlib.resources.files("jobscout") / "web"` so it works from an installed wheel. API routes keep their paths. `GET /health` unchanged.
  - `GET /searches/{id}/questions/{question_id}` → `Question` (`conversation.question_for`), 404 for another user's search, 422 for an unknown id. The summary's edit icon uses it.
  - `pipeline.filters.work_mode_of(job: Job) -> Literal["remote", "hybrid", "onsite"] | None` — `remote` when `job.remote`, else the posting's stated mode (today's private `_stated_on_premises_mode`), else `None`. `JobRead.work_mode` carries it (computed when building the read model, not stored).
  - `sources.registry.all_source_statuses(settings) -> list[SourceStatus]` — the configured sources as `source_statuses` returns them, followed by every other registered source with `active=False, reason="off"`. `GET /status` returns this list; `GET /sources` is unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_page_is_served_at_the_root(client): ...  # 200, text/html, "jobscout" in body, no-cache header
def test_the_design_system_is_served(client): ...  # /static/design/tokens.css 200 text/css; /static/design/logos/jobscout-mark.svg 200
def test_the_api_still_answers_beside_the_page(client): ...  # /health, /status
def test_a_question_can_be_read_by_id(client): ...  # GET /searches/{id}/questions/level -> options intern..any
def test_reading_a_question_of_another_users_search_is_404(client): ...
def test_work_mode_of(): ...  # remote job -> "remote"; "Hybrid" in title -> "hybrid"; nothing stated -> None
def test_job_read_carries_the_work_mode(client): ...
def test_status_lists_off_sources_after_the_configured_ones(client, monkeypatch): ...  # SOURCES=himalayas -> himalayas active, then the others "off"
```

- [ ] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/api/test_web.py tests/api/test_searches.py tests/api/test_status.py tests/pipeline/test_filters.py tests/sources/test_registry.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement as listed under Interfaces; move the design folder with `git mv` if tracked, a plain move otherwise, and fix the relative paths inside `examples/index.html`**

- [ ] **Step 4: Run the full Python gate, then `uv build` and check the wheel lists `jobscout/web/design/tokens.css` and `jobscout/web/index.html`**

Run: `uv build --wheel && python -c "import zipfile,glob; n=zipfile.ZipFile(sorted(glob.glob('dist/*.whl'))[-1]).namelist(); print([x for x in n if '/web/' in x][:20])"`
Expected: the web files are listed. Delete `dist/` afterwards.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: serve the page and the design system, and expose what the page needs"
```

---

### Task 3: The page's foundation — DOM, i18n, API client, icons, layout, sidebar

**Files:**
- Create: `src/jobscout/web/js/dom.js`, `js/i18n.js`, `js/api.js`, `js/icons.js`, `js/router.js`, `js/sidebar.js`, `js/store.js`, `src/jobscout/web/locales/en.json`, `locales/pt-BR.json`, `tests/web/dom.test.js`, `tests/web/i18n.test.js`, `tests/web/api.test.js`, `tests/web/README.md` (one line: run with `node --test tests/web/`), `tests/test_web_assets.py`
- Modify: `src/jobscout/web/index.html`, `app.js`, `app.css`, `.github/workflows/ci.yml` (add `actions/setup-node` pinned to Node 20 and a `node --test tests/web/` step)

**Interfaces:**
- Produces (every later task builds on these):
  - `dom.js`: `h(tag: string, attrs?: object, ...children): HTMLElement` — string/number children become **text nodes**; `null`/`false` children are skipped; arrays are flattened; attrs: `class`, `on<Event>` (listener), `aria-*`, `data-*`, boolean attributes, `href` (only via `safeUrl`, see Task 7 — until then `h` sets `href` as given and Task 7 routes posting links through `safeUrl`). `mount(parent, ...children)` replaces a node's children. No `innerHTML` anywhere in `dom.js`.
  - `icons.js`: `icon(name: string): SVGElement` from a fixed map of Lucide outlines (stroke 1.5–2, `currentColor`, 16/20 px): `search, plus, settings, bookmark, bookmark-filled, pencil, check, check-circle, clock, loader, alert-triangle, info, external-link, x, eye-off, minus, rotate-ccw, lock, chevron-down, trash, menu`. The only file allowed to use `innerHTML` (static strings).
  - `i18n.js`: `loadLocale(code) -> Promise<void>` (fetches `/static/locales/<code>.json`), `t(key, params?) -> string` (`{name}` placeholders; a missing key returns the key itself and logs once), `currentLocale()`. Plural-free: copy is written to avoid plurals ("{n} jobs").
  - `api.js`: `api.get(path)`, `api.post(path, body?)`, `api.put(path, body)`, `api.patch(path, body)`, `api.del(path)` → parsed JSON (or `null` for 204); non-2xx throws `ApiError { status, code, detail, searchId }` built by `apiError(status, body)` from FastAPI's `{"detail": ...}` and this API's `{"detail", "code", "search_id"}` bodies.
  - `store.js`: a tiny shared state `{ status, searches }` with `refreshStatus()`, `refreshSearches()` and `subscribe(fn)`.
  - `router.js`: hash routes `#/` (home), `#/search/<id>`, `#/my-jobs`, `#/settings`; `onRoute(fn)`, `go(path)`. Unknown routes fall back to home.
  - `sidebar.js`: logo lockup (`design/logos/jobscout-mark.svg` + `jobscout`), `New search` (secondary button with `plus`), the `Searches` heading and list (most recent first, open one highlighted with `aria-current="page"`, the running one marked with a `loader` icon and visually hidden text), the empty line `Your searches appear here`, a divider, `My jobs` (`bookmark`), and `Settings` (`settings`) at the bottom. Each search item has a `trash` ghost button shown on hover/focus that turns the row into `Delete this search?` with `Delete`/`Cancel` (no browser dialogs); a 409 shows `Another search is running.`.
  - `app.css`: the shell grid (sidebar 260 px | main), the main column widths (720/1000 px), the pinned composer slot, the detail-panel slot, and the < 800 px rules. Tokens only.
  - `app.js`: loads status and locale, applies the theme, renders the sidebar and the route's view (views are stubs until Tasks 4–8: each route shows its title).
  - `index.html` sets `data-theme` from `localStorage['jobscout.theme']` (default `dark`) in an inline `<script>` before CSS paints, inside `try/catch`.

- [ ] **Step 1: Write the failing tests**

```js
// tests/web/dom.test.js — run in node with a minimal fake document (write one in tests/web/fake-dom.js: createElement, createTextNode, appendChild, setAttribute, addEventListener, textContent)
test("string children become text, not markup", ...)  // h("p", {}, "<img onerror=x>").childNodes[0].nodeType === 3
test("null and false children are skipped; arrays flatten", ...)
test("on* attributes attach listeners", ...)
// tests/web/i18n.test.js
test("t fills placeholders", ...)        // t("found", {n: 3}) === "Found 3 jobs that fit."
test("a missing key returns the key", ...)
// tests/web/api.test.js
test("apiError reads this API's 409 body", ...)  // {detail:"Another search is running", code:"search_busy", search_id:4} -> code "search_busy", searchId 4
test("apiError reads FastAPI's validation body", ...)  // 422 with detail list -> code null, detail string
```
```python
# tests/test_web_assets.py
def test_locales_have_the_same_keys_and_placeholders(): ...  # en.json vs pt-BR.json: same key set; each value's {placeholders} identical
def test_no_page_code_writes_html_from_data(): ...  # no "innerHTML", "outerHTML", "insertAdjacentHTML" in web/**/*.js except js/icons.js
def test_page_css_uses_tokens_only(): ...  # app.css has no "#rgb/#rrggbb" literals and no "px" outside an allowlist of layout widths (260, 720, 1000, 800, 480)
```

- [ ] **Step 2: Run them and see them fail**

Run: `node --test tests/web/` and `uv run pytest tests/test_web_assets.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement as listed under Interfaces**

- [ ] **Step 4: Run both gates; then start the app (`uv run jobscout serve`) and load `http://127.0.0.1:8000/` — the sidebar renders in both themes with no console errors; `#/my-jobs` and `#/settings` show their stubs**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: the page's shell, sidebar, i18n and API client"
```

---

### Task 4: Home and settings (screens 01, 02, 08, 10)

**Files:**
- Create: `src/jobscout/web/js/views/home.js`, `js/views/settings.js`, `js/composer.js`
- Modify: `app.js`, `app.css`, both locale files
- Test: `tests/web/composer.test.js`

**Interfaces:**
- Consumes: Task 3's `h`, `icon`, `t`, `api`, `store`, `router`.
- Produces:
  - `composer.js`: `composer({ placeholder, disabled, locked, multiline, submitLabel, onSubmit }) -> { el, focus(), setText(s), setPlaceholder(s), setDisabled(b) }` — the pinned composer used by every view (`locked` shows the `lock` icon and the "choose an option" placeholder, as in `03`). Enter submits, Shift+Enter adds a line; an empty or whitespace text never submits. Pure helper `shouldSubmit(text, { disabled }) -> boolean`.
  - **Home (`#/`):** the `text-display`-sized heading `What job are you looking for?`, the large composer (multiline, primary `Start search`), centred. With `status.llm_key_found == false`: the notice of `08` above the field (`info` icon, two lines, `How to set it up` linking to the README's setup section on GitHub), the field still accepts text, `Start search` disabled. Submitting `POST /searches {paragraph}` → `go("#/search/<id>")` and `refreshSearches()`. A 409 `no_llm_key` shows the same notice. While the request is in flight the button reads `Searching…` and is disabled (the reading takes seconds).
  - **Settings (`#/settings`):** sections `Model` (provider, chat model, embeddings in `.text-meta`, status `Key found` with `check-circle` in `--success` or `No key found` in `--danger`, footnote), `Sources` (one row per `status.sources`: display name, a short description from i18n keyed by source name — Himalayas/Remotive "Remote jobs worldwide", LinkedIn "Searched by country, slower", Indeed "Searched by country", Arbeitnow "Jobs in Germany, no search" — and an `Active`/`Off` tag with icon; a `missing …` reason shows as the description), `Appearance` (segmented `Dark`/`Light`, writes `localStorage` and `data-theme`; segmented `English`/`Português`, `PUT /me/locale`, then reloads strings and re-renders). Read-only otherwise; nothing here edits `.env`.

- [ ] **Step 1: Write the failing tests**

```js
test("an empty or whitespace text never submits", ...)   // shouldSubmit("  \n", {}) === false
test("a disabled composer never submits", ...)
test("text submits", ...)
```

- [ ] **Step 2: Run them and see them fail** — `node --test tests/web/composer.test.js`

- [ ] **Step 3: Implement**

- [ ] **Step 4: Verify against the screens** — run the demo seed (Task 6 has not run yet: use an empty database) and compare: home with no searches (`01`), with searches (`02`, after creating one with a key set), without a key (`08`: unset `GOOGLE_API_KEY`), settings (`10`); both themes, both locales. Both gates clean.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: the home screen, the no-key notice and settings"
```

---

### Task 5: The conversation (screens 03, 04; reading errors; refinements)

**Files:**
- Create: `src/jobscout/web/js/views/search.js` (the search page; this task renders the conversation part), `js/transcript.js`, `js/conversation.js`
- Modify: `app.js`, `app.css`, both locale files
- Test: `tests/web/transcript.test.js`

**Interfaces:**
- Consumes: `GET /searches/{id}` (`SearchRead`: `paragraph, refinements, reading, reading_error, asked, answers, question, summary, confirmed, widenings, latest_run`), `POST /searches/{id}/answers {question, choice, values}`, `POST /searches/{id}/refinements {text}`, `POST /searches/{id}/reread`, `GET /searches/{id}/questions/{qid}` (Task 2), `GET /status` (sources line).
- Produces:
  - `transcript.js` (pure, no DOM): `buildTranscript(search) -> Entry[]` where `Entry` is one of `{kind:"user", text}`, `{kind:"gotit", what, asking: bool}`, `{kind:"error", text}`, `{kind:"question", question, answered: Answer|null, active: bool}`, `{kind:"summary", summary, confirmed}`. Order: the paragraph, then each refinement as a user entry; then `error` if `reading_error`, else `gotit`; then one `question` entry per id in `asked` (answered, greyed) each followed by a user entry with the answer's label; then the active question (if `search.question`) or the summary. `gotitWhat(search) -> {role, skills, place}` (role = `summary.role`, skills = `summary.skills` (else `reading.required_skills`), place = city/country/"anywhere"/abroad) and `answerLabel(qid, answer, t) -> string` ("Remote, Hybrid", "Anywhere in Brazil", "Recife").
  - `conversation.js` renders entries with `h()`: app lines start with the `search` icon in `--accent-text`; user bubbles right-aligned on `--surface`; the counter `{n} of {total}` in `.text-meta` above the active question; option chips as `js-btn--secondary` small buttons with `aria-pressed`. **Single-choice questions answer on click; multi-choice ones toggle chips and show `Continue`** (the screen's one primary button; `Don't mind` clears the others). An `other` option focuses the composer with the placeholder `Type a country`/`Type a city` and the next submit answers that question (`choice` `country` or `city`, `values:[text]`); a 422 shows its message under the question. The role question (`typed`) unlocks the composer; its submit is a refinement.
  - The summary card (`04`): rows Role (the terms as tags), Level, Work mode, Location (city, country, `Anywhere`, or `Not {country}` for abroad), Skills (only when non-empty), each with a `pencil` ghost button that loads `GET …/questions/{qid}` and shows that question inline below the card; the footer `{n} sources: {names}` (active sources from `/status`) and `Search jobs` (primary; wired in Task 7 — here it is rendered and disabled with a `title`).
  - Composer on this page: locked with `Choose an option above to continue` while a choice question is active; otherwise `Type an answer or add a detail` (`Add a detail to refine this search` once results exist), and a submit is `POST …/refinements` (refining never starts a search).
  - Reading error: one line (`alert-triangle`, `--danger`) with the error text and a `Try again` secondary button → `POST …/reread`.
  - Every mutation re-renders from the returned `SearchRead`; after a render the view scrolls to the last entry.

- [ ] **Step 1: Write the failing tests**

```js
test("paragraph, then got-it, then answered questions, then the active one", ...)
test("refinements follow the paragraph as user entries", ...)
test("a reading error replaces the got-it line", ...)
test("with no question pending the summary closes the transcript", ...)
test("answer labels", ...)  // work_modes pick [remote,hybrid] -> "Remote, Hybrid"; city anywhere with Brazil -> "Anywhere in Brazil"; city Recife -> "Recife"; level any -> "Don't mind"
test("got-it place reads city, country, anywhere and abroad", ...)
```
Use fixtures shaped exactly like `SearchRead` JSON (copy one from a real `GET /searches/{id}` response into `tests/web/fixtures/search-asking.json` and `search-ready.json`).

- [ ] **Step 2: Run them and see them fail** — `node --test tests/web/transcript.test.js`

- [ ] **Step 3: Implement**

- [ ] **Step 4: Verify against `03` and `04`** with a real key: create a search from the paragraph in `03`, answer level, pick two work modes and Continue, answer location, see the summary; edit a row; add a refinement ("only hybrid") and see the summary update without a search starting. Both themes, both locales. Both gates clean.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: the search conversation, its questions and the summary"
```

---

### Task 6: Demo data for checking the screens

The remaining screens need runs, matches and verdicts in known states. A seed script makes them reproducible without a key or a network, for verification now and for README screenshots later.

**Files:**
- Create: `scripts/seed_demo.py`, `tests/test_seed_demo.py`

**Interfaces:**
- Produces: `uv run python scripts/seed_demo.py <path.db>` refuses an existing file, creates a fresh database (`init_db`), the default user, and searches built through the real pipeline functions (`add_search`, `save_conversation`, `confirm`, `record_fetched`, direct `Match`/`Run` rows):
  1. "Junior AI Engineer" — confirmed, a finished ok run with `sources` for four sources, 12 jobs with scores 92→55 (titles, companies, locations, salaries and `posted_at` as in `06`/`07`, `reasoning`/skills/red flags filled), 9 fetched jobs left unscored (so `waiting == 9`), two matches `saved`, one `applied`.
  2. "Remote Python backend" — confirmed, results, one job shared with search 1 at a lower score (My jobs shows it once, naming both).
  3. "Data analyst for a friend" — confirmed, a finished run with zero results and nothing waiting, one source `failed` with detail `"SourceBlocked: 429 Too Many Requests"` (screen `09`), city "Recife", on-site, junior.
  4. "Frontend in Lisbon" — mid-conversation: reading present, `work_modes` answered, the location question active (screen `03`-like).
  5. "Data engineer" — an interrupted run (unfinished, `finished_at` null) to show the interrupted state.
  It prints how to serve it: `DATABASE_URL=sqlite:///<path> SCHEDULER_ENABLED=false GOOGLE_API_KEY=demo uv run jobscout serve`.

- [ ] **Step 1: Write the failing test**

```python
def test_seed_builds_every_state(tmp_path): ...
    # run main([str(tmp_path / "demo.db")]); open it; assert: 5 searches; search 1 found == 12 and count_waiting == 9;
    # list_my_jobs counts == {"all": ..., "saved": 2, "applied": 1}; search 3 latest run has a failed source and zero results;
    # search 4 has a pending question; search 5 latest run unfinished
def test_seed_refuses_an_existing_file(tmp_path): ...
```

- [ ] **Step 2: Run it and see it fail** — `uv run pytest tests/test_seed_demo.py -v`

- [ ] **Step 3: Implement** (`scripts/` is not a package; the test imports it with `runpy` or `importlib.util.spec_from_file_location`). No network, no LLM; fixed timestamps relative to "now" so "2d ago" reads naturally.

- [ ] **Step 4: Run it, serve it, and confirm the sidebar lists the five searches** — Python gate clean.

- [ ] **Step 5: Commit**

```bash
git commit -m "chore: a demo database for checking the page's screens"
```

---

### Task 7: Running, results and the job detail (screens 05, 06, 07, 09)

**Files:**
- Create: `src/jobscout/web/js/format.js`, `js/runview.js`, `js/results.js`, `js/detail.js`, `js/jobcard.js`
- Modify: `js/views/search.js`, `js/conversation.js` (wire `Search jobs`), `app.css`, both locale files
- Test: `tests/web/format.test.js`, `tests/web/runview.test.js`

**Interfaces:**
- Consumes: `POST /searches/{id}/run` and `/rank` (202 `{run_id}`; 409 `questions_pending` / `search_busy`), `GET /searches/{id}/runs/{run_id}` (`RunRead` with `counters` and `sources`, Task 1), `GET /searches/{id}/matches` (`{matches, found, waiting}`), `PATCH /matches/{id} {status}`, `/status.running_search_id`.
- Produces:
  - `format.js` (pure): `safeUrl(url) -> string|null` (only `http:`/`https:` via `new URL`), `timeAgo(iso, now, t) -> "2d ago"` (minutes/hours/days/weeks), `salary(job, locale) -> string|null` (`null` when both bounds are missing; compact numbers with the currency: "R$ 6–8 mil", "$40–55k"), `scoreLabel(score) -> "92%"`, `sourceName(id) -> "LinkedIn"`.
  - `runview.js` (pure): `runView(search, run, matchList, runningSearchId) -> { state, ... }` with `state` one of `none` (no run), `running` (unfinished and `runningSearchId === search.id`), `interrupted` (unfinished and not running), `results` (`found > 0`), `waiting_only` (`found == 0 && waiting > 0`), `nothing` (`found == 0 && waiting == 0`); plus `failures` (sources with `state` `failed`/`skipped`, for the lines under the results) and `progress` (`{sources, scored, toScore}`).
  - `jobcard.js`: `jobCard(match, { selected, onOpen, searches? })` — the design system's JobCard: title (`js-card__title`), `company · location`, tags (source; `REMOTE`/`HYBRID`/`ON-SITE` from `job.work_mode`; never invented seniority), meta line (salary · time ago; on My jobs also the search titles), score `js-tag--match` top right; `aria-selected` for the open card.
  - **Search jobs / Search again / Rank the rest:** `Search jobs` (summary card, primary) calls `/run`; `Search again` (secondary, `rotate-ccw`) calls `/run`; `Rank the rest` (secondary) calls `/rank`. A 409 `search_busy` shows `Another search is running.` with a link to `#/search/<search_id>`; nothing else changes.
  - **Running (`05`):** the summary's button becomes a disabled `Searching…` with `loader`; below, `Searching {n} sources.` and one row per `run.sources` (`check-circle` done · `n jobs`; `loader` searching · `term i of n` in `--info`; `clock` waiting; `alert-triangle` failed; `minus` skipped), then a progress bar (`--info`) with `Scoring {scored} of {toScore} jobs` once scoring starts. `aria-live="polite"` on the status line. Polls `GET …/runs/{run_id}` and `GET …/matches` every 2 s while `state == running`; cards appear and **reorder by score** as matches arrive; polling stops on any other state and when the view is left.
  - **Results (`06`):** the main column widens to 1000 px; the line `Found {n} jobs that fit.` (+ ` {m} more are waiting for a score.` and `Rank the rest` when `waiting > 0`); the cards; failure lines under the results (`{source} did not answer ({detail}). The other sources still ran.` for `failed`; the skip reason for `skipped`); `Search again`.
  - **Waiting only:** `No scores yet. {m} jobs are waiting for a score.` with `Rank the rest`.
  - **Nothing found (`09`):** `No jobs matched. I searched {n} sources and found {m} postings, but none fit {what}.` (`m` = `counters.fetched`, `what` from the summary: level, work mode, place), failure lines, `Try widening the search:` with one secondary chip per `search.widenings` (labels per widening id; clicking `POST …/answers` with the widening's answer and re-renders the summary — it does not search), and `Search again`.
  - **Interrupted:** `This search stopped before it finished.` with `Search again`.
  - **Detail (`07`):** opening a card shows the right panel (480 px; full screen below 800 px; `x` closes; Escape closes; focus moves into it and back): `text-h1` title, `company · location`, tags, score + `Fit score · {time ago}`, `reasoning` (as text), `Matches` (✓ list), `Missing` (– list), `Watch out` (`alert-triangle` list), then `Open posting` (primary link with `external-link`, only when `safeUrl` returns a URL), `Save`/`Saved` (secondary toggle with `bookmark`/`bookmark-filled`), `Mark as applied` (ghost, `check-circle`), `Dismiss` (ghost, `eye-off`). A verdict `PATCH`es and updates the card (dismissed/applied leave the default listing; the panel says so and offers to close).

- [ ] **Step 1: Write the failing tests**

```js
test("safeUrl keeps http and https only", ...)   // "javascript:alert(1)" -> null; "https://x.io/a" -> same; "not a url" -> null
test("timeAgo", ...)                              // 2 days before now -> "2d ago"; 5 hours -> "5h ago"
test("salary is omitted without bounds and compact with them", ...)
test("runView: unfinished and running here is running", ...)
test("runView: unfinished but not running is interrupted", ...)          // Review Focus 3
test("runView: results, waiting only and nothing", ...)
test("runView: failed and skipped sources become failures", ...)
```

- [ ] **Step 2: Run them and see them fail** — `node --test tests/web/format.test.js tests/web/runview.test.js`

- [ ] **Step 3: Implement**

- [ ] **Step 4: Verify against `05`, `06`, `07`, `09`** — with the demo database: search 1 (`06`, open a card for `07`, save one, dismiss one), search 3 (`09`, click a widening and see the summary change without a search), search 5 (interrupted); then with a real key, run a real search to see `05` live and the cards reorder. A job whose URL is `javascript:` (edit one demo row) shows no `Open posting`. Both themes, both locales. Both gates clean.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: run a search and show its progress, results and job detail"
```

---

### Task 8: My jobs (screens 11, 12)

**Files:**
- Create: `src/jobscout/web/js/views/myjobs.js`
- Modify: `app.js`, `app.css`, both locale files

**Interfaces:**
- Consumes: `GET /my-jobs?tab=&search_id=` (`{items: [{match, searches:[{id,title}]}], counts}`), `jobCard`, `detail` (Task 7), `GET /searches` (filter options).
- Produces: `#/my-jobs` with the `text-h1` title `My jobs`; tabs `All {n}` / `Saved {n}` / `Applied {n}` (a `tablist`; the selected tab underlined in `--brand`; counts in `.text-meta`); a `select` `All searches` + one option per search; cards via `jobCard` with the search titles in the meta line and a `bookmark-filled` mark on saved ones; opening a card shows the same detail panel; a verdict refreshes the list and counts. Empty tab: centred two lines — `No saved jobs yet.` / `Save a job from a search's results and it appears here.` (and equivalents for All and Applied). The sidebar's `My jobs` entry is `aria-current` here. The selected tab and filter stay in the hash (`#/my-jobs?tab=saved&search=2`).

- [ ] **Step 1: Verify against `11` and `12`** with the demo database (no pure logic is added here, so no new node test; the route and verdict calls reuse tested modules): All lists the shared job once naming both searches; Saved and Applied match the seeded counts; filtering by search narrows the list and the counts; an empty tab shows `12`'s copy. Both themes, both locales. Both gates clean.

- [ ] **Step 2: Commit**

```bash
git commit -m "feat: My jobs, across every search"
```

---

### Task 9: Screen-by-screen check, mobile, accessibility, docs

**Files:**
- Modify: whatever the check finds in `src/jobscout/web/`; `README.md` (a "Using the page" section: `uv run jobscout serve`, open `http://127.0.0.1:8000`, what the conversation asks, where My jobs and Settings are; the demo seed command for contributors); `CLAUDE.md` ("Current state": the page is done; "Commands": the seed script and `node --test tests/web/`)

- [ ] **Step 1: Walk all twelve screens** against their PNGs with the demo database (and a real key for `03`–`05`), in dark and light, in English and Português. Record each deviation in the task report as `screen · what differs · fixed/kept (why)`. The mockups' sample data (counts, "anthropic", São Paulo/Rio buttons, seniority tags, the sidebar clock) are not deviations (spec §2, §4, §5.3).
- [ ] **Step 2: Check the 800 px breakpoint** (one column, sidebar behind `menu`, full-screen detail) and keyboard use: every control reachable with Tab, visible `--focus` ring, Enter/Space activate chips, Escape closes the detail, the composer keeps focus after an answer.
- [ ] **Step 3: Check the Review Focus items by hand:** a demo job titled `<img src=x onerror=alert(1)>` renders as text; a `javascript:` URL shows no link; stop the server mid-search, restart it, reopen the search — interrupted, no polling in the network tab; start a second search while one runs — `Another search is running.`; switch the language with results on screen — UI switches, explanations stay.
- [ ] **Step 4: Fix what Steps 1–3 found; both gates clean**
- [ ] **Step 5: Commit**

```bash
git commit -m "fix: match the page to its screens; document using it"
```

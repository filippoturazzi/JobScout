# Results Grid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a search's results as the three best in a highlighted row plus a paged three-column grid (9 per page), followed by the jobs that have no score yet.

**Architecture:** A new pipeline function lists a search's unscored jobs with their stored similarity; `GET /searches/{id}/matches` returns them as `unscored`. On the page, a new pure module turns scored + unscored into a page of highlighted cards, grid cards and a divider; `runView` gains the unscored list and folds `waiting_only` into `results`; `results.js` renders the grid, divider and pager.

**Tech Stack:** Python 3.12, SQLModel, FastAPI, pytest; plain ES modules, Node's `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-11-results-grid-design.md`

## Global Constraints

- The LLM cap stays at 15 (`MAX_LLM_EVALUATIONS_PER_RUN`); nothing here calls the LLM or the embedding provider.
- 9 grid cards per page; page 1 also holds up to 3 highlighted cards, which do not count toward the 9.
- A job appears in exactly one group. A stale row that still has a score stays in the scored group.
- Unscored order: similarity descending; jobs with no usable vector last, in `select_candidates` order (freshest first).
- Similarity is never shown as a number on a card.
- UI: tokens only (`var(--...)`), both themes, read `src/jobscout/web/design/DESIGN.md` first. Breakpoint literals in `@media`/`@container` are allowed, as `app.css` already does.
- Copy in both `web/locales/en.json` and `web/locales/pt-BR.json` (same keys and placeholders, enforced by `tests/test_web_assets.py`).
- Architecture: selection in `pipeline/`, router stays thin. `ruff check`, `ruff format --check`, `mypy src`, pytest and `node --test tests/web/*.test.js` clean before each commit.

## Review Focus

1. **A search whose profile has no embedding yet** (never ran matching, or `EMBEDDING_DIM` changed): every unscored job has `similarity=None` and the list still renders, freshest first. Test in Task 1.
2. **The list shrinks under the user** (a verdict removes a card, a refinement empties the scored group) while on page 3 of 3: the page clamps to the last page, never an empty page. Test in Task 3.
3. **Exactly 3 scored and no unscored**: one page, highlighted row only, no grid, no divider, no pager. Test in Task 3.
4. **The scored group ends exactly on a page boundary** (3 + 9 scored, 5 unscored): the divider opens page 2, not the bottom of page 1. Test in Task 3.
5. **An unscored job open in the detail panel gets scored by a ranking run**: the panel must not crash on a job that moved groups; it keeps showing the job. Test in Task 5.

---

### Task 1: Pipeline: list a search's unscored jobs

**Files:**
- Modify: `src/jobscout/pipeline/run.py` (beside `count_waiting`)
- Test: `tests/pipeline/test_run.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass
  class Unscored:
      job: Job
      similarity: float | None
      match_id: int | None

  def list_unscored(session: Session, search_id: int, limit: int = 500) -> list[Unscored]
  ```

Selection (one function, no provider calls):
- (a) jobs from `select_candidates(session, prefs, search_id)` whose row is missing or is stale **with `score is None`** (drop candidates whose stale row has a score);
- (b) `Match` rows of this search with `status == "low"`, job active, `job_matches_preferences(job, prefs)`;
- drop any job of group (a) with no row in this search for which the user has a row in **any** search with status in `CLOSED_STATUSES`;
- similarity: a `low` row's `match.similarity`; otherwise `cosine(unpack(job.embedding), unpack(prefs.profile_embedding))` when both exist and `dim()` agrees, else `None`;
- sort by similarity descending, `None` last keeping input order (stable sort); cut to `limit`.

- [ ] **Step 1: Write the failing tests** in `tests/pipeline/test_run.py`, building rows with `make_search`, `upsert_jobs`, `fetched` and `Match(...)` as the neighbouring tests do, and vectors with `jobscout.matching.vectors.pack`:
  - `test_list_unscored_includes_unevaluated_and_low_jobs`: a fetched job with no row, a `low` row (similarity 0.3), a scored `new` row → result job external_ids are exactly the first two; the low one has `match_id` set, the unevaluated one `None`.
  - `test_list_unscored_keeps_scored_stale_rows_out`: a stale row with `score=70` → not in the list; a stale row with `score=None` → in it.
  - `test_list_unscored_orders_by_similarity_with_unknown_last`: profile embedding `pack([1, 0])`, jobs with embeddings `pack([0.6, 0.8])`, `pack([1, 0])`, none → order is `[1,0]` (1.0), `[0.6,0.8]` (0.6), no-vector (`None`).
  - `test_list_unscored_without_profile_embedding_has_no_similarity`: prefs `profile_embedding=None` → every `similarity is None`, list not empty.
  - `test_list_unscored_hides_jobs_closed_in_another_search`: job fetched by search A with no row in A; search B has a `dismissed` row for it → not in A's list. A `saved` row in B → still listed.
  - `test_list_unscored_hides_inactive_and_unselected_jobs`: an inactive `low` job and a `low` job the preferences reject → absent.
  - `test_list_unscored_does_not_embed`: pass nothing that embeds; assert by construction (the function takes no `Embeddings`), and that `job.embedding` stays `None` after the call.

- [ ] **Step 2: Run them to verify they fail**
  Run: `uv run pytest tests/pipeline/test_run.py -k list_unscored -v`
  Expected: FAIL with `ImportError: cannot import name 'list_unscored'`.

- [ ] **Step 3: Implement `Unscored` and `list_unscored`** in `src/jobscout/pipeline/run.py` per the selection above. Import `cosine, dim, unpack` from `jobscout.matching.vectors`.

- [ ] **Step 4: Run the tests to verify they pass**
  Run: `uv run pytest tests/pipeline/test_run.py -v`
  Expected: PASS (old tests included).

- [ ] **Step 5: Commit**
  ```bash
  git add src/jobscout/pipeline/run.py tests/pipeline/test_run.py
  git commit -m "feat: list a search's unscored jobs with their stored similarity"
  ```

### Task 2: API: `unscored` in the matches listing

**Files:**
- Modify: `src/jobscout/api/schemas.py` (`MatchList`, new `UnscoredRead`)
- Modify: `src/jobscout/api/routers/searches.py:247-271`
- Test: `tests/api/test_searches.py`

**Interfaces:**
- Consumes: `list_unscored(session, search_id, limit=DEFAULT_LISTING_LIMIT)` from Task 1.
- Produces (JSON): `MatchList { matches, found, waiting, unscored: [UnscoredRead] }`, `UnscoredRead { job: JobRead, similarity: float | null, match_id: int | null }`.

- [ ] **Step 1: Write the failing tests**
  - `test_matches_include_unscored_jobs`: one scored match, one fetched job with no row, one `low` row → `body["unscored"]` has 2 items, each with `job.id`, `similarity`, `match_id`; `found == 1`; `waiting` equals `count_waiting` (1).
  - `test_matches_unscored_is_empty_when_everything_is_scored`: → `body["unscored"] == []`.
  - Update `test_matches_report_found_and_waiting` only if it asserts the exact key set.

- [ ] **Step 2: Run them to verify they fail**
  Run: `uv run pytest tests/api/test_searches.py -k "unscored" -v`
  Expected: FAIL with `KeyError: 'unscored'`.

- [ ] **Step 3: Add `UnscoredRead` and the `unscored: list[UnscoredRead]` field; fill it in `read_search_matches`** via `read_job(item.job)` (from `api/routers/jobs.py` or wherever `read_match` gets it). Always sent, whatever `status`/`min_score` are.

- [ ] **Step 4: Run the API tests**
  Run: `uv run pytest tests/api -v`
  Expected: PASS.

- [ ] **Step 5: Commit**
  ```bash
  git add src/jobscout/api/schemas.py src/jobscout/api/routers/searches.py tests/api/test_searches.py
  git commit -m "feat: return unscored jobs beside a search's matches"
  ```

### Task 3: Page: the pure results layout

**Files:**
- Create: `src/jobscout/web/js/resultslayout.js`
- Test: `tests/web/resultslayout.test.js`

**Interfaces:**
- Produces:
  ```js
  export const PER_PAGE = 9;
  export const HIGHLIGHTED = 3;
  // scored: MatchRead[] best first; unscored: UnscoredRead[] in API order; page: 1-based.
  // -> { highlighted: MatchRead[], items: Item[], page: number, pages: number }
  // Item = { kind: "match", match } | { kind: "divider" } | { kind: "unscored", item }
  export function resultsLayout(scored, unscored, page)
  ```

Rules: `highlighted = scored.slice(0, 3)` on page 1 only, `[]` on later pages. The cards to paginate are `scored.slice(3)` then `unscored`, 9 per page; `pages = max(1, ceil(cards / 9))`. `page` is clamped to `[1, pages]`. The divider is inserted immediately before the first unscored card on the page that holds it; no divider when `unscored` is empty.

- [ ] **Step 1: Write the failing tests** (`node:test`, `assert/strict`, same import style as `runview.test.js`):
  - 15 scored, 0 unscored, page 1 → 3 highlighted, 9 match items, `pages == 2`; page 2 → 0 highlighted, 3 items.
  - 2 scored, 0 unscored → 2 highlighted, `items == []`, `pages == 1`.
  - 3 scored, 0 unscored → 3 highlighted, `items == []`, `pages == 1` (Review Focus 3).
  - 0 scored, 4 unscored → 0 highlighted, items = divider + 4 unscored.
  - 5 scored, 65 unscored, page 1 → items = 2 match, divider, 7 unscored (9 cards + divider); `pages == 8`.
  - 12 scored, 5 unscored: page 1 has 9 match items and no divider; page 2 starts with the divider (Review Focus 4).
  - page 9 of a list with 3 pages → `page == 3` (Review Focus 2); page 0 → 1.

- [ ] **Step 2: Run them to verify they fail**
  Run: `node --test tests/web/resultslayout.test.js`
  Expected: FAIL, module not found.

- [ ] **Step 3: Implement `resultsLayout`** in `src/jobscout/web/js/resultslayout.js`.

- [ ] **Step 4: Run them to verify they pass**
  Run: `node --test tests/web/resultslayout.test.js`
  Expected: PASS.

- [ ] **Step 5: Commit**
  ```bash
  git add src/jobscout/web/js/resultslayout.js tests/web/resultslayout.test.js
  git commit -m "feat: page layout for highlighted, grid and unscored results"
  ```

### Task 4: Page: `runView` states with unscored jobs

**Files:**
- Modify: `src/jobscout/web/js/runview.js`
- Modify: `src/jobscout/web/js/views/search.js:102` (`isWide`), and the three `api.get(\`/searches/${id}/matches\`)` calls (lines ~67, ~155, ~166) to add `?limit=500`
- Test: `tests/web/runview.test.js`

**Interfaces:**
- Consumes: the API shape from Task 2.
- Produces: `runView(...)` result gains `unscored: UnscoredRead[]` (always `[]` while `state === "running"`) and `widen: boolean`. State `waiting_only` no longer exists: finished with `found > 0 || unscored.length > 0` is `results`; `nothing` only when both are 0. `widen = found === 0 && waiting === 0` (the only-`low` case). `isWide(v)` stays `v.state === "results" || (running && matches.length)`.

- [ ] **Step 1: Update/add tests** in `tests/web/runview.test.js` (`list()` helper gains an `unscored` argument defaulting to `[]`):
  - replace the `waiting_only` assertion: `list(0, 9, [], nine unscored)` → `results`;
  - `list(0, 0, [], two unscored)` → `results`, `widen === true`;
  - `list(3, 4, matches, unscored)` → `widen === false`;
  - `list(0, 0, [], [])` → `nothing`;
  - running run with unscored in the list → `v.unscored` deep-equals `[]`;
  - a list without the `unscored` key (older payload) → `v.unscored` is `[]`, no throw.

- [ ] **Step 2: Run to verify the new ones fail**
  Run: `node --test tests/web/runview.test.js`
  Expected: FAIL on the replaced `waiting_only` test and the new ones.

- [ ] **Step 3: Implement in `runview.js`; add `?limit=500` to the three fetches in `views/search.js`.** Remove the `waiting_only` case and its copy usage from `results.js` in Task 5, not here; this task only changes the view model (results.js still compiles because its `waiting_only` branch is simply unreachable).

- [ ] **Step 4: Run all page tests**
  Run: `node --test tests/web/*.test.js`
  Expected: PASS.

- [ ] **Step 5: Commit**
  ```bash
  git add src/jobscout/web/js/runview.js src/jobscout/web/js/views/search.js tests/web/runview.test.js
  git commit -m "feat: run view carries unscored jobs and folds waiting-only into results"
  ```

### Task 5: Page: render the grid, divider, pager and unscored detail

**Files:**
- Modify: `src/jobscout/web/js/results.js` (`cards`, `results` and `waiting_only` cases)
- Modify: `src/jobscout/web/js/jobcard.js` (options `excerpt`, `unscored`; card key)
- Modify: `src/jobscout/web/js/detail.js` (no score / no verdict buttons when `match.id == null`)
- Modify: `src/jobscout/web/js/views/search.js` (`ui.page`, `onPage`, `openMatch` keying)
- Modify: `src/jobscout/web/app.css`
- Modify: `src/jobscout/web/locales/en.json`, `src/jobscout/web/locales/pt-BR.json`
- Test: `tests/web/detail.test.js`

**Interfaces:**
- Consumes: `resultsLayout` (Task 3), `runView().unscored/.widen` (Task 4).
- Produces:
  - `jobCard(match, { selected, onOpen, searches, excerpt = false, unscored = false })`. `excerpt` adds `match.reasoning` in a `.jc-reason` paragraph clamped to 2 lines; `unscored` shows a `js-tag` with `t("no_score")` where the score goes.
  - `cardKey(match) -> string`: `String(match.id)` when it has one, else `` `job-${match.job.id}` ``; used for `data-match-id`, `ui.selectedId`, and the refocus query in `search.js`.
  - `asMatch(item: UnscoredRead) -> object`: `{ id: null, score: null, reasoning: null, matched_skills: [], missing_skills: [], red_flags: [], status: "new", similarity: item.similarity, job: item.job, unscored: true }`, exported from `results.js` so the detail panel can open an unscored job.
  - handlers gain `onPage(n)`; `ui` gains `page` (starts at 1).

Rendering of `results` (top to bottom): the "found" line (no "more waiting" sentence any more); when `widen`, the widening chips (same markup as `nothing`); the highlighted row (label `t("best_for_you")`, `.run-top`, cards with `excerpt: true`) on page 1; the grid `.run-grid` with `role="listbox"` holding match cards, the divider (`.run-divider`: `t("unscored_divider", {n: unscored.length})`, then, if `waiting > 0`, `t("can_score", {m: waiting})` and the existing "Rank the rest" button), and unscored cards; the pager (`nav.run-pager`, `aria-label` `t("pages")`: previous, numbered buttons with `aria-current="page"` on the current one, next; hidden when `pages == 1`); failures; "Search again"; notices. `running` keeps its cards but renders them through the same grid (no highlighted row, no divider, no pager: all of the run's scored cards in score order). Changing page scrolls the run area's top into view.

CSS (`app.css`, tokens only): `.run { container-type: inline-size; }`; `.run-grid, .run-top { display: grid; gap: var(--space-4); grid-template-columns: repeat(3, minmax(0, 1fr)); }`; `@container (max-width: 720px)` → 2 columns; `@container (max-width: 480px)` → 1 column; `.run-divider { grid-column: 1 / -1; }`; `.run-top .js-card` uses `--accent-subtle`/`--border-strong` for emphasis; `.jc-reason` with `-webkit-line-clamp: 2`.

Copy (en / pt-BR):
- `best_for_you`: "Best for you" / "Melhores para você"
- `unscored_divider`: "Still unscored ({n})" / "Ainda sem nota ({n})"
- `can_score`: "{m} can still be scored" / "{m} ainda podem receber nota"
- `no_score`: "No score" / "Sem nota"
- `pages`: "Pages" / "Páginas"
- `page_prev`: "Previous page" / "Página anterior"
- `page_next`: "Next page" / "Próxima página"
- `page_n`: "Page {n}" / "Página {n}"
Delete `waiting_only` and `more_waiting` if nothing else uses them (grep first).

- [ ] **Step 1: Write the failing tests** in `tests/web/detail.test.js` (its fake DOM):
  - opening `asMatch(item)` renders the title and the "Open posting" link, no `.dt-score`, no `[data-action="save"]` or dismiss button;
  - `detail.update(scoredMatch)` on a panel opened with an unscored match shows the score (Review Focus 5: a ranking scored it), no throw.

- [ ] **Step 2: Run to verify they fail**
  Run: `node --test tests/web/detail.test.js`
  Expected: FAIL (verdict buttons present / `asMatch` missing).

- [ ] **Step 3: Implement** jobcard options and `cardKey`, `asMatch`, detail's `id == null` branch, `results.js` rendering, `search.js` (`ui.page`, `onPage`, keying by `cardKey`; when a poll or ranking changes the list, keep `ui.page` and let `resultsLayout` clamp it), CSS, copy.

- [ ] **Step 4: Run every check**
  Run: `node --test tests/web/*.test.js; uv run pytest; uv run ruff check .; uv run ruff format --check .; uv run mypy src`
  Expected: all PASS / clean.

- [ ] **Step 5: See it**: `uv run python scripts/seed_demo.py demo.db` then `DATABASE_URL=sqlite:///demo.db uv run jobscout serve`; open a search with results in both themes at 1280 px, 900 px with the detail panel open, and 375 px. Expected: 3 / 2 / 1 columns, highlighted row on page 1 only, divider and "Sem nota" cards after the scored ones, pager works, clicking an unscored card opens its details. If the demo database has no unscored jobs, add some to `scripts/seed_demo.py` (fetched jobs with no match row, and a `low` row) and its test in `tests/test_seed_demo.py`.

- [ ] **Step 6: Commit**
  ```bash
  git add src/jobscout/web tests/web scripts/seed_demo.py tests/test_seed_demo.py
  git commit -m "feat: results as a highlighted row, a paged grid and unscored jobs"
  ```

### Task 6: Docs

**Files:**
- Modify: `CLAUDE.md` (API line: `GET /searches/{id}/matches` also returns `unscored`)
- Modify: `docs/superpowers/specs/2026-11-11-results-grid-design.md` (status: implemented)

- [ ] **Step 1: Edit both; run `uv run pytest tests/test_web_assets.py`** (expected PASS).
- [ ] **Step 2: Commit**
  ```bash
  git add CLAUDE.md docs/superpowers/specs/2026-11-11-results-grid-design.md
  git commit -m "docs: results grid and the unscored listing"
  ```

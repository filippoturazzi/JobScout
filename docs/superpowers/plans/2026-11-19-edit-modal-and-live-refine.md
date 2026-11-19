# Edit Modal and Live Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The pencil on a summary row opens a modal, and after the first search a refinement or a saved edit updates the results by itself, with the results always last in the column.

**Architecture:** The backend gains one thing: a `role` answer in `pipeline/conversation.py`. Everything else is the page. A new `js/editmodal.js` holds the dialog and its pure helpers. `runView` learns to keep the previous results, dimmed, while an update runs. `views/search.js` chains the endpoints that already exist (answers or refinements, then `stop` if a run is in flight, then `run` once nothing is pending).

**Tech Stack:** Python 3.12, FastAPI, pytest; plain ES modules, `node --test`.

**Spec:** `docs/superpowers/specs/2026-11-19-edit-modal-and-live-refine-design.md`

**Deviation from the spec (Task 6 records it):** the spec's "my call" was one backend call that saves and runs together. The plan chains the existing endpoints from the page instead. Starting a run while this search runs is already refused by `_run_in_flight` (`api/routers/searches.py:56`), and the stop is asynchronous, so a one-call endpoint would need a restart queue in the scheduler. The page already polls until the run ends, so it can start the next run then. If the run cannot start, the page shows the existing `request_failed` toast, and "Search again" stays under the results.

## Global Constraints

- Read `src/jobscout/web/design/DESIGN.md` before any UI work. Tokens only (`var(--...)`, `js-*` classes), never a literal colour or size. Both themes work (dark is the default).
- Copy goes in both `web/locales/en.json` and `web/locales/pt-BR.json`.
- No framework, no build step, no new packages.
- `uv run ruff check .`, `uv run ruff format .`, `uv run mypy src`, `uv run pytest` and `node --test tests/web/*.test.js` are clean before every commit.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A refinement typed while a run is in flight.** The run stops, the refinement is saved, and exactly one new run starts once the old one has ended. A second refinement typed before the old run ends must not start two runs. The test goes in Task 5 (`nextStep` while running with a run already queued).
2. **A refinement or edit that opens a new question** (hybrid now needs a city). No run starts until it is answered, and the run starts right after the answer. The tests go in Task 5 (`nextStep` with a pending question, and with the question answered).
3. **A role typed as an empty string or as only commas.** The modal refuses it without calling the API, and the API answers 422. The tests go in Task 1 (`InvalidAnswerError`) and Task 2 (`answerFor` returns null).
4. **An edit made before the first search.** No run starts, and the summary just updates. The test goes in Task 5 (`nextStep` with `hasRun: false`).
5. **An update run where nothing has been scored yet.** The old cards stay dimmed instead of disappearing, then are replaced by the first fresh score. The tests go in Task 4.

---

### Task 1: The role is answerable

**Files:**
- Modify: `src/jobscout/pipeline/conversation.py` (`_validated`, `answer`, `pending`, `_is_pending`, `summary`, `title`)
- Test: `tests/pipeline/test_conversation.py`, `tests/api/test_searches.py`

**Interfaces:**
- Produces: `POST /searches/{id}/answers` accepts `{"question": "role", "choice": "role", "values": ["<text>"]}`. The text is split on commas into terms (stripped, empty ones dropped, deduplicated in order). It is stored as `Answer(choice="role", values=terms)`. `summary(c).terms` and `.role` come from that answer when it exists, otherwise from the reading.

- [ ] **Step 1: Write the failing tests** in `tests/pipeline/test_conversation.py`. Replace `test_the_role_is_not_answerable` with:

```python
def test_the_role_only_takes_a_role_answer():
    with pytest.raises(InvalidAnswerError):
        answer(conv(terms=[]), "role", Answer(choice="ai engineer"))

def test_a_typed_role_becomes_the_terms():
    c = answer(conv(), "role", Answer(choice="role", values=["Data Engineer, analytics engineer "]))
    assert summary(c).terms == ["Data Engineer", "analytics engineer"]
    assert summary(c).role == "Data Engineer"
    assert "role" not in c.asked  # an edit from the summary, not a transcript question
    assert c.confirmed is False

def test_an_empty_role_is_refused():
    for text in ["", "  ", " , ,"]:
        with pytest.raises(InvalidAnswerError):
            answer(conv(), "role", Answer(choice="role", values=[text]))

def test_a_typed_role_beats_a_new_reading():
    c = answer(conv(), "role", Answer(choice="role", values=["data engineer"]))
    c = with_reading(c, reading(terms=["ml engineer"]))
    assert summary(c).terms == ["data engineer"]

def test_a_typed_role_answers_the_role_question():
    c = answer(conv(terms=[], suggested_skills=["python"]), "role", Answer(choice="role", values=["qa"]))
    assert "role" not in pending(c)

def test_the_title_follows_a_typed_role():
    c = answer(conv(), "role", Answer(choice="role", values=["data engineer"]))
    assert title(c).endswith("Data Engineer")
```

In `tests/api/test_searches.py`, following the fixtures that file already uses to make a read search: `test_answering_the_role_sets_the_terms` (POST answers with a role gives 200 and `summary.terms == ["data engineer"]`) and `test_an_empty_role_is_422`.

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run pytest tests/pipeline/test_conversation.py tests/api/test_searches.py -k role -v`
Expected: the new tests FAIL, because `_validated` has no `role` case.

- [ ] **Step 3: Implement it in `conversation.py`**
  - Add a private `_terms(c: Conversation) -> list[str]`: the `role` answer's values if there is one, else `c.reading.terms`, else `[]`.
  - Use `_terms` in `summary`, `title` and `pending`. In `_is_pending`, assert `_terms(c)` instead of `r.terms`.
  - Add `case "role":` to `_validated`. It needs `a.choice == "role"`, exactly one value, `c.reading is not None`, and at least one term after splitting. Otherwise raise `InvalidAnswerError`.
  - In `answer`, leave `asked` alone when `qid == "role"`.
  - Update `answer`'s docstring: the role is answered only from the summary's edit.

- [ ] **Step 4: Run them and confirm they pass**, then run the whole suite with ruff and mypy.

Run: `uv run pytest -q; uv run ruff check .; uv run mypy src`
Expected: everything passes and both tools are clean.

- [ ] **Step 5: Commit**: `feat: answer the role from the summary's edit`

---

### Task 2: The modal's pure helpers

**Files:**
- Create: `src/jobscout/web/js/editmodal.js`
- Modify: `src/jobscout/web/js/conversation.js` (export `singleAnswer`)
- Test: `tests/web/editmodal.test.js`

**Interfaces:**
- Consumes: the `Question` from `GET /searches/{id}/questions/{qid}` (`{id, multi, typed, options: [{choice, value}]}`), and `singleAnswer(option)` from `conversation.js`.
- Produces:
  - `editKind(q) -> "text" | "single" | "multi"`: `role` is `"text"`, `q.multi` is `"multi"`, everything else is `"single"`.
  - `answerFor(q, sel) -> {choice, values} | null`. `sel` is `{ option: Option | null, picked: string[], any: boolean, text: string }`. It returns null when Save must stay disabled.
  - `initialSelection(q, answer, summary) -> sel`: the selection the modal opens with. The role's text is `summary.terms.join(", ")`. Multi starts from a `pick` or `any` answer. Single starts from the option whose `choice` (plus `value`, when the option has one) matches the stored answer.

- [ ] **Step 1: Write the failing tests** in `tests/web/editmodal.test.js`:

```js
test("role is typed, work mode and skills are multi, the rest single", ...)
// editKind({id:"role",multi:false}) === "text"; {id:"work_modes",multi:true} → "multi"; {id:"level"} → "single"; {id:"city"} → "single"

test("a typed role sends one value, trimmed; blank sends nothing", ...)
// answerFor(role, {text:"  data engineer "}) → {choice:"role", values:["data engineer"]}; text "  " → null

test("multi sends pick, or any, or nothing when empty", ...)
// picked ["remote","hybrid"] → {choice:"pick", values:["remote","hybrid"]}; any → {choice:"any", values:[]}; neither → null

test("single sends the option's answer; 'other' sends the typed place", ...)
// level option {choice:"junior"} → {choice:"junior", values:[]}
// country option {choice:"country", value:"Brazil"} → {choice:"country", values:["Brazil"]}
// city + other + text "Recife" → {choice:"city", values:["Recife"]}; location + other + "Chile" → {choice:"country", values:["Chile"]}
// other with blank text → null; no option → null

test("the modal opens on the current answer", ...)
// role: initialSelection(role, undefined, {terms:["ai engineer","python"]}).text === "ai engineer, python"
// work_modes answer {choice:"pick", values:["remote"]} → picked ["remote"]
// level answer {choice:"junior"} → option.choice === "junior"
```

- [ ] **Step 2: Run them and confirm they fail.**

Run: `node --test tests/web/editmodal.test.js`
Expected: FAIL, because the module does not exist.

- [ ] **Step 3: Implement the three helpers** in `editmodal.js`, and export `singleAnswer` from `conversation.js` (it is unchanged).

- [ ] **Step 4: Run them and confirm they pass.**

Run: `node --test tests/web/*.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**: `feat: the edit modal's selection and answer rules`

---

### Task 3: The modal itself, opened by the pencil

**Files:**
- Modify: `src/jobscout/web/js/editmodal.js` (add `openEditModal`)
- Modify: `src/jobscout/web/js/conversation.js` (remove the `ui.editing` / `conv-edit` block from `renderEntries`)
- Modify: `src/jobscout/web/js/views/search.js` (`onEdit`, `ui.editing`)
- Modify: `src/jobscout/web/app.css` (remove `.conv-edit`, add the `.edit-modal` styles)
- Modify: `src/jobscout/web/locales/en.json`, `pt-BR.json`
- Test: `tests/web/transcript.test.js` or `conversation`-level tests, if any assert on `conv-edit`

**Interfaces:**
- Consumes: `editKind`, `answerFor`, `initialSelection` (Task 2), and `optionLabel` and `questionText` from `conversation.js`.
- Produces: `openEditModal(q, { country, answer, summary, onSave }) -> { close(): void, showError(text: string): void, busy(on: boolean): void }`. `onSave(answer)` returns a Promise. The modal does not close itself on Save: the caller closes it once the API accepts the answer.

- [ ] **Step 1: Read `design/DESIGN.md` and the confirm-delete dialog** (`sidebar.js:17-53`, `app.css:128`). The modal follows the same pattern: `<dialog>`, `showModal()`, the backdrop click and Esc close it, and `onclose` removes it.

- [ ] **Step 2: Implement `openEditModal`**
  - The heading is `questionText(q.id, country)`.
  - **text:** a `js-input` field holding `sel.text`. Enter saves.
  - **single:** the `conv-chip` chips with `aria-pressed`, one selected at a time. Picking `other` shows a text field below the chips, with the placeholder `type_city` or `type_country`.
  - **multi:** the same chips with toggling, where `any` clears the others (as in `questionBlock`).
  - The footer has `cancel` (ghost) and `save` (primary). Save is disabled while `answerFor` returns null or while `busy(true)` is set.
  - An error line with `role="alert"` uses the existing `conv-error` class.
  - On open, focus goes to the first field or chip. The caller returns focus to the pencil (the dialog's close event).
  - New copy keys: `save` ("Save" / "Salvar") and `cancel` ("Cancel" / "Cancelar"). Reuse a key when it already exists.

- [ ] **Step 3: Wire it in `views/search.js`**
  - `onEdit(qid)` fetches the question as it does today, then calls `openEditModal`.
  - `onSave` posts to `/searches/{id}/answers`.
    - On 422 it calls `showError(detail)` and the modal stays open.
    - On success it closes the modal, sets `search` and redraws.
    - If `search.question` is now set (an edit created a need), it opens the modal for that question.
  - Drop `ui.editing` and the inline `conv-edit` block.
  - The modal never touches the composer, so the "other" path no longer goes through the composer when you edit. `ui.otherFor` stays for questions asked in the conversation.

- [ ] **Step 4: Run all checks.**

Run: `node --test tests/web/*.test.js; uv run pytest tests/test_web_assets.py -q`
Expected: PASS.

- [ ] **Step 5: Check it by hand.** Seed a demo database with `uv run python scripts/seed_demo.py demo.db` and serve it with `DATABASE_URL=sqlite:///demo.db uv run jobscout serve`. Open a search that has a summary and click each row's pencil in both themes:
  - the role field;
  - the level chips;
  - the work-mode multi chips;
  - Location → Other → typing a place;
  - a 422 shown inside the modal;
  - Esc and the backdrop close it, and focus goes back to the pencil.

- [ ] **Step 6: Commit**: `feat: edit a summary row in a modal`

---

### Task 4: Results stay last, and the old ones stay dimmed while updating

**Files:**
- Modify: `src/jobscout/web/js/runview.js` (`runView` gets a 5th parameter)
- Modify: `src/jobscout/web/js/transcript.js` (`buildTranscript`)
- Modify: `src/jobscout/web/js/results.js` (`runSection`: the refined line and the dimmed cards)
- Modify: `src/jobscout/web/app.css`, locales
- Test: `tests/web/runview.test.js`, `tests/web/transcript.test.js`, `tests/web/results.test.js`

**Interfaces:**
- Produces:
  - `runView(search, run, matchList, runningSearchId, previous = null)`. While `state === "running"`, if the run has scored nothing yet and `previous` has items, `matches` is `previous` and `updating` is `true`. Otherwise `updating` is `false`. `previous` is ignored in every other state.
  - `buildTranscript` stops emitting refinement bubbles once `search.latest_run` is set. Before any run they stay as they are today.
  - `refinedLine(search, view) -> Element | null`, in `results.js`. When `search.latest_run` is set and `search.refinements` is not empty, it shows `refined` ("Refined: {text}" / "Refinado: {text}"), plus ` · ` and `updating` ("updating…" / "atualizando…") while running. It is the first child of the running, results and nothing states.

- [ ] **Step 1: Write the failing tests**
  - `runview.test.js`: `"an update keeps the previous cards until the first fresh score"`. This test covers running with no fresh match and `previous=[a,b]` (gives `matches` `[a,b]` and `updating` true) and running with one fresh match (gives that match and `updating` false). Also `"previous is ignored once the run has finished"`.
  - `transcript.test.js`: `"refinements leave the transcript once a run exists"`. It uses `search-ready.json` with `refinements: ["only remote"]` and `latest_run: {id: 1}`, and checks that no entry has `text === "only remote"`. The existing test `"refinements follow the paragraph as user entries"` keeps passing (no run).
  - `results.test.js`: `"the refined line shows the latest refinement, and updating while running"`.

- [ ] **Step 2: Run them and confirm they fail.**

- [ ] **Step 3: Implement it.** In `runSection`'s running case, when `view.updating` is true, wrap the cards in `run-cards run-cards--dim`. The new rule is `.run-cards--dim { opacity: var(--...) }`, using an existing opacity or disabled token from `tokens.css`. If none exists, add one to `tokens.css` and `tokens.json`. Add `aria-busy="true"` to the dimmed wrapper.

- [ ] **Step 4: Run them and confirm they pass**, with the whole web suite.

- [ ] **Step 5: Commit**: `feat: keep results last and dim the old ones while they update`

---

### Task 5: A refinement or edit after the first search runs it again

**Files:**
- Create: `src/jobscout/web/js/liverefine.js`
- Modify: `src/jobscout/web/js/views/search.js` (`submitText`, `onSave` from Task 3, `onAnswer`, `poll`, `startRun`, `draw`)
- Modify: `src/jobscout/web/js/composer.js` (typing allowed while running)
- Test: `tests/web/liverefine.test.js`, `tests/web/composer.test.js`

**Interfaces:**
- Produces: `nextStep({ hasRun, running, queued, question }) -> "none" | "ask" | "stop" | "wait" | "run"`. It is pure and is called after every save:
  - `hasRun` false gives `"none"` (before the first search nothing runs by itself).
  - A `question` that is not null gives `"ask"` (the run waits for the answer, and `queued` stays set).
  - `running` and not `queued` gives `"stop"`. The caller posts `/stop` and sets `queued`.
  - `running` and `queued` gives `"wait"` (the stop is already asked; never two runs).
  - Otherwise it gives `"run"`.
- `composer({ running, ... })`: while running, the field is editable. The button is Stop while the field is empty and Send once it has text. Esc still stops.

- [ ] **Step 1: Write the failing tests**
  - `liverefine.test.js`: one `test` per row of the table above, plus `"a queued run starts once the question is answered and nothing runs"`, which checks that `{hasRun:true, running:false, queued:true, question:null}` gives `"run"`.
  - `composer.test.js`: `"while running, typing turns Stop into Send"`. With `running: true`, the field is not disabled. After you set text and fire `input`, the button has `type="submit"`. Submitting calls `onSubmit`.

- [ ] **Step 2: Run them and confirm they fail.**

- [ ] **Step 3: Implement `nextStep`** and the composer change. Update the composer's header comment, which says the field is locked while running.

- [ ] **Step 4: Wire it in `views/search.js`**
  - Add `ui.queued = false` and `ui.previous = null`.
  - Write `afterChange()`. It runs after a refinement from the composer, after a Save in the modal, and after an answer in the conversation while `ui.queued` is set. It switches on `nextStep(...)`:
    - `"ask"`: set `ui.queued = true` only when `hasRun`.
    - `"stop"`: set `ui.queued = true` and call `api.post(/stop)`, the same as `stopRun` does.
    - `"run"`: set `ui.queued = false`, set `ui.previous` to the current `view().matches`, then `startRun("run")`.
    - `"none"` and `"wait"`: do nothing.
  - In `poll()`, when the run has finished, `ui.queued` is set and `search.question` is null, call `afterChange()`.
  - Pass `ui.previous` to `runView`, and clear it when a run finishes.
  - `hasRun` is `Boolean(ui.run)`. `running` is `view().state === "running"`.
  - `submitText` while running: send the refinement (allowed during a run, because it does not touch the preferences), then `afterChange()`.
  - The composer placeholder while running and not stopping becomes `composer_running_refine` ("Searching… type to refine, or press Esc to stop" / "Buscando… digite para refinar, ou Esc para parar").

- [ ] **Step 5: Run all checks.**

Run: `node --test tests/web/*.test.js; uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Check it by hand.** You need a real provider key, because a run calls the LLM. Run `uv run jobscout serve` and open a search with results:
  - Refine "only remote": old cards dim, "Refined: only remote · updating…" appears, and fresh cards replace them.
  - Refine again mid-run: one stop, then one new run.
  - Refine "hybrid" with no city: the city question shows, and the run starts after the answer.
  - Edit Level in the modal: it runs again.
  - Before the first search, an edit starts no run.

- [ ] **Step 7: Commit**: `feat: a refinement or edit after the first search runs it again`

---

### Task 6: Docs follow the code

**Files:**
- Modify: `docs/superpowers/specs/2026-11-19-edit-modal-and-live-refine-design.md` (replace the "one backend call" call with the page chaining the endpoints, and give the reason from this plan's header)
- Modify: `docs/superpowers/specs/2026-11-07-chat-interface-design.md` step 6 (one line: amended by the 2026-11-19 spec; refining after the first search runs again)
- Modify: `src/jobscout/api/routers/searches.py` (the `refine_search` docstring says "Never runs the search", which stays true of the endpoint; add "the page runs it after the first search")
- Modify: `CLAUDE.md` (the API line: answers also take the role)

- [ ] **Step 1: Make the edits above.**
- [ ] **Step 2: Run the full verification set from Global Constraints.**
- [ ] **Step 3: Commit**: `docs: live refinement and the role answer`

# Edit modal and live refinement

Date: 2026-11-19. Amends `2026-11-07-chat-interface-design.md` (step 6 of the flow, and the
summary's edit icon).

## Intent

On a search's page the results are the point, and they always sit at the bottom of the
column. Two things break that today:

- The pencil on a summary row reopens the question **inside the conversation**, between the
  summary and the results (`conversation.js:222`).
- A refinement typed in the composer is drawn as a bubble **at the top**, right under the
  first paragraph (`transcript.js:57`), and it does not change the results: the old results
  stay until someone clicks "Search again".

What the user wants: editing happens in a modal, and refining (or editing) updates the
results by itself, while the results stay at the bottom.

## Goals

- The pencil on each summary row opens a modal for that question. A typed question shows a
  text field; a choice question shows only its chips.
- After the first search, a refinement or a saved edit updates the results without a click.
- The results are always the last thing in the column. No part of the conversation appears
  below them.

## Non-goals

- Instant local filtering of the current results (approach B) and mixing filtering with
  searching again (approach C).
- New questions or new answer kinds, apart from editing the role (below).
- Asking questions about a single job from the composer.

## Anti-goals

- A refinement that changes nothing visible. If the user refines, the results must visibly
  start updating.
- Several searches piling up because the user made several edits in a row.

## Approaches

- **A. Refine, then search again (picked).** Any refinement or saved edit updates the
  summary, confirms it, and starts a full run (fetch and scoring). The old results stay on
  screen, dimmed, until new scores replace them. It does what the user expects, stays
  predictable, and reuses the "Search again" path: saving preferences already marks the
  search's matches stale (`pipeline/run.py:400`), and a run scores them again. The cost is a
  full run's time and LLM calls for every refinement.
- B. Filter what was already fetched. Instant and free, but a new role or new skills bring
  nothing new, and the old scores ignore the refinement.
- C. Filter for filter-type changes, search again for role and skills. Fastest in every case,
  but the most complex, and the user cannot predict which behaviour they will get.

The user picked A.

## Design

### The edit modal

- A `<dialog>` opened with `showModal()`, following the pattern in `palette.js` and
  `sidebar.js`: the title is the question text, then the body, then Cancel and Save.
  Esc, a click on the backdrop and Cancel all close it without saving.
- The body depends on the question:
  - **Role**: a text field holding the current role.
  - **Level**: the single-choice chips. A click selects one, and Save sends it.
  - **Work mode, Skills**: the multi-choice chips, the same as today's `questionBlock`.
  - **Location / Country / City**: the chips. "Other city/country" shows a text field
    inside the modal instead of using the composer.
- Save posts the answer (`POST /searches/{id}/answers`). A validation error is shown inside
  the modal, and the modal stays open. The modal closes on success.
- The inline `conv-edit` block below the summary goes away.
- Tokens and `js-*` classes only, both themes, copy in `en.json` and `pt-BR.json`.

### Editing the role (backend)

Today the role only comes from reading the paragraph: `_validated` has no `role` case. Add a
`role` answer (`choice: "role", values: [text]`) that sets the role, and the search terms,
to what was typed, without an LLM call. Like every clicked answer, it wins over a later
reading. *My call:* this is cheaper and more predictable than sending the text through as a
refinement and reading it again.

### Live refinement (approach A)

- **Before the first search** (no run yet): nothing changes. Edits and refinements update the
  summary, and "Search jobs" starts the search.
- **After the first search**: a refinement from the composer, or a Save in the modal, does
  the following in order:
  1. Updates the conversation (the existing endpoints).
  2. If a new question became necessary (for example, hybrid now needs a city), asks it, in
     the modal when the question came from an edit and in the conversation otherwise. The
     run starts only after it is answered.
  3. Confirms the summary as preferences and starts a run (`POST /searches/{id}/run`).
- **While a run is in progress**: a new refinement stops it (the existing stop), then starts
  a new run with everything asked so far. A run in progress is never doubled.
- **Old results while it runs**: they stay, dimmed, under a line "Updating…". Cards are
  replaced as new scores arrive, as a running search does today.
- **As built:** the page chains the existing endpoints (answers or refinements, then `stop`
  while a run is in flight, then `run` once nothing is pending). The first draft of this spec
  called for one backend call, but `run` is refused while this search runs and the stop is
  asynchronous, so a single call would have needed a restart queue in the scheduler. The page
  already polls until the run ends, so it starts the next run then. If that start fails, the
  usual `request_failed` toast shows and "Search again" stays under the results.
- A run waiting on a question scrolls that question into view, since it sits above the
  results.

### Where a refinement appears

A refinement is no longer drawn as a bubble at the top. A quiet line just above the results
records it: "Refined: only remote · updating…", and after the run: "Refined: only remote".
*My call:* only the latest refinement is shown there. All of them are kept in the
conversation (`search.refinements`), as today.

## Constraints

- `DESIGN.md` rules: tokens only, both themes, en and pt-BR copy.
- Dependencies point down: the page calls the API, and the API calls `pipeline`.
- TDD: pipeline tests for the role answer and for refine-then-run, and `node --test` for the
  modal's pure parts (which body each question gets, and what each answer sends).

## Left to the builder

- Whether the run is started by a flag on the existing endpoints or by a new one.
- The modal's exact layout within the design system.
- Focus handling: focus moves into the modal on open and returns to the pencil on close.

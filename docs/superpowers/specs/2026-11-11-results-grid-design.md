# Results grid: best three, a paged grid, and the unscored jobs

Date: 2026-11-11. Status: implemented (plan `docs/superpowers/plans/2026-11-11-results-grid.md`).

## Why

A search found about 80 jobs and the page showed 15 cards, one per row, so the user had to
scroll a long way to see them, and the other ~65 were not on the page at all. The user
believed the jobs that were never scored could include good ones, and could not see them.

Two things came out of the conversation:

1. The page is too tall. The user wants to see the best jobs first, compactly.
2. Jobs without a score should be visible, after the scored ones, not hidden.

## Decided by the user

- **The LLM cap stays at 15** (`MAX_LLM_EVALUATIONS_PER_RUN`). Scoring everything was
  offered and declined. "Rank the rest" keeps working as it does now.
- **Layout B** of the mockups (`.superpowers/brainstorm/…/layout.html`): the three
  best-scored jobs in a highlighted row at the top, each showing a short excerpt of the
  LLM's reasoning; below them the rest in a three-column grid, best score first, **9 per
  page** with pagination.
- **Unscored jobs appear after the scored ones**, in the same grid and pagination.
- **Clicking an unscored job opens its details** (description, link) like any other job.
  No per-job "score this one" action.

## Behaviour

### Order of the list

One list, in this order:

1. Scored matches (the current default listing: `score` not null, not dismissed/applied,
   active, passing the preferences), by score descending, then similarity.
2. A divider, "Still unscored (N)", then the unscored jobs: (a) jobs the search fetched
   that have no match row yet, or a stale row **with no score**, and (b) `low` matches,
   the ones the cosine prefilter turned away without calling the LLM. Ordered by
   similarity to the profile, descending; jobs with no embedding yet go last, freshest
   first (the order `select_candidates` already uses).

A job appears in exactly one group. *Builder's-check call:* a stale row that still has
a score (after a content change or a refinement) stays in group 1 with its old score, as
today; it is not in group 2. A job with no row in this search that the user dismissed or
applied to in **another** search is hidden from group 2 (a verdict is about the job, and
`_upsert_match` already copies it across searches), so the selection looks up the user's
verdicts across searches.

The three highlighted cards are the first three of group 1, and they appear only on page 1.
With fewer than three scored matches, only those are highlighted; with none, there is no
highlighted row and the page starts at the divider.

### Pagination

- 9 cards per page in the grid. Page 1 holds the highlighted row (up to 3) **plus** 9 grid
  cards; later pages hold 9 grid cards. The divider sits wherever the scored group ends, so
  a page can hold scored cards, the divider, then unscored cards.
- Controls under the grid: previous, page numbers, next. Hidden when there is one page.
- Pagination is client-side over the full list the API returns (the listing is already
  capped at 500, `DEFAULT_LISTING_LIMIT`).
- A new run, a ranking, or a verdict that changes the list keeps the user on the current
  page if it still exists, otherwise the last page.

### Cards

- Highlighted card: the current `jobCard` plus one or two lines of `reasoning`, clamped
  with an ellipsis. Visually stronger (border/elevation from the design tokens).
- Grid card: the current `jobCard`, unchanged.
- Unscored card: the current `jobCard` with a "No score" tag in the place of the score.
  Similarity is **not** shown as a number, so it is never confused with the LLM score.

### Grid

Three columns when the content column is wide enough, two on narrower widths, one on a
phone (below the existing 800 px breakpoint). The search page's results area uses the
wide column (`app-column--wide`, 1000 px) whenever it shows results, so three columns fit.

### "Rank the rest"

The button moves to the divider. When it runs, newly scored jobs leave the unscored group
and take their place among the scored ones.

*Builder's-check call:* ranking only rescores `waiting` jobs; `low` rows are not
re-queued (changing that is the prefilter, a non-goal). So the button shows only when
`waiting > 0`, and its line says how many it acts on, e.g. "Still unscored (65) ·
40 can still be scored · Rank the rest". With `waiting == 0` the divider has no button.

### Run states

*Builder's-check call:*

- **Running:** unchanged. Only the run's own scored cards, entering the grid in score
  order as scores arrive; **no unscored group while a run is in flight** (that list grows
  on every poll and would shift pages under the user).
- **Finished, at least one job scored or unscored:** the grid. `waiting_only` becomes
  this state (no highlighted row, page 1 starts at the divider).
- **Finished, scored = 0 and only `low` unscored jobs:** the grid starting at the divider,
  and the widening chips stay, placed **above** the divider (the jobs below them did not
  pass the prefilter, so widening is still the useful suggestion).
- **Nothing at all fetched:** `nothing`, unchanged.
- **Interrupted / none:** unchanged.

### Detail panel for an unscored job

Opens the same panel: title, company, posted, link, description. No score, no reasoning,
no skills. Whether it offers Save / Dismiss: see "Left to the builder".

## Backend

`GET /searches/{id}/matches` gains an `unscored` list next to `matches`:

```
MatchList { matches: [MatchRead], found: int, waiting: int, unscored: [UnscoredRead] }
UnscoredRead { job: JobRead, similarity: float | null, match_id: int | null }
```

- `similarity` comes from the stored embeddings (the `low` match row's own `similarity`,
  or cosine of the job's stored embedding against the profile's for a job with no row).
  Computing it reads stored vectors only; it never calls the embedding provider.
- `match_id` is set for `low` rows (they have one), null for jobs never evaluated.
- `waiting` keeps its meaning (jobs "Rank the rest" would score); the divider's N is
  `len(unscored)`.
- The selection lives in `pipeline` (beside `list_matches` / `count_waiting`), the router
  stays thin. Respects the same filters as the default listing (active, preferences,
  dismissed/applied hidden).

## Copy

New keys in `web/locales/en.json` and `pt-BR.json`: the divider ("Still unscored ({n})" /
"Ainda sem nota ({n})"), the "No score" tag ("Sem nota"), the highlighted row's label
("Best for you" / "Melhores para você"), pagination labels (previous, next, page n of m)
for assistive tech.

## Non-goals

- Scoring more than 15 per run, or changing the prefilter threshold.
- Scoring a single job on demand.
- Changing "My jobs".
- Server-side pagination.

## Anti-goals

- Showing similarity as if it were a score.
- A page that is taller than today's for the same results.

## Tests

- `pipeline`: the unscored selection (no-row jobs, unscored stale rows, `low` rows; a
  scored stale row is not in it; a job dismissed/applied in another search is not in it;
  filters; ordering by similarity with no-embedding jobs last; no embedding provider call).
- `tests/web`: the run states above (running shows no unscored group; former
  `waiting_only`; only-`low` with widening chips; Rank button hidden when `waiting == 0`).
- API: `unscored` in the response, `found`/`waiting` unchanged.
- `tests/web`: the pure layout function (split into highlighted / grid pages / divider
  position for 0, 2, 3, 15 scored and 0, 65 unscored; page clamping after the list
  shrinks).

## Left to the builder

- Exact card styling within the tokens and DESIGN.md.
- How the highlighted row collapses on narrow screens (one column like the grid is fine).
- Whether an unscored job's detail panel offers Save/Dismiss when it has a `match_id`.

# Stage 5 — Real sources and a local dashboard: Design Spec

**Date:** 2026-10-22
**Status:** Approved for planning
**Parent spec:** `docs/superpowers/specs/2026-09-19-jobscout-design.md` (amends §4, §5, §7)
**Supersedes:** the roadmap's "stage 5 = more sources" and parts of "stage 6 = Reflex UI, i18n"

## 1. Purpose

Make JobScout useful to a stranger who clones it.

Today it collects from one German job board, scores everything 0–35, and has no
face. The parent spec's success criterion for this stage is narrow — more sources —
but the honest problem is wider: **nobody can use this yet.** Stage 5 closes that.

Someone clones the repo, runs `uv sync`, pastes an LLM key, opens a page, writes one
paragraph describing the job they want, and watches matching jobs arrive ranked by
score. No account, no e-mail, no hosted service, no build step.

### 1.1 What changed since the roadmap was written

Three decisions from earlier stages are reopened here, deliberately and with the
user's approval. They are listed up front because a reader of the old roadmap will
otherwise think this document contradicts the project.

| Was | Now | Why |
|---|---|---|
| Stage 6 frontend is **Reflex** | FastAPI serves static HTML/CSS/JS | The UI moved from an afterthought to the product's face, and the project now has a real design system. Reflex generates React and abstracts the CSS; applying tokens means fighting the abstraction. Serving a page from the API that already exists removes a dependency and a build step from everyone who clones. |
| Stage 6 does **i18n** | English and pt-BR ship in stage 5, default English | The UI is the first thing a stranger sees. A pt-BR-only interface loses nearly everyone who is not Brazilian, and the job corpus is majority international. `User.locale` already exists with default `"en"`, so this costs almost nothing now and costs a rewrite later. |
| Stage 4's digest is the product's output | The **dashboard** is the output; e-mail goes dormant | The user decided they do not want an e-mail system for now. Nothing is deleted: without `SMTP_HOST` the digest is already a silent no-op, so it simply never appears for anyone who clones. Removing it would cost more than leaving it. |

## 2. Decisions

| Topic | Decision | Rationale |
|---|---|---|
| Scraping | **Still forbidden.** No LinkedIn, no Gupy. | LinkedIn has no public jobs API; its Jobs API is partner-only, and every "LinkedIn jobs API" on offer is scraping in a wrapper. Gupy's official API is OAuth partner access for ATS integration, not job search; the JSON routes third-party scrapers use are undocumented. For a portfolio project, a collector that violates terms of use is a liability, not a showcase — it is the first thing an attentive interviewer prods. The user confirmed the rule stands. |
| Source tiers | **Keyless sources ship enabled. Keyed sources are optional and unlock Brazil.** | Preserves "paste one LLM key and run" while still answering "I need Brazilian jobs". A source whose credentials are absent does not register, and nothing breaks. |
| Query model | Sources are **searched by term**, not dumped as catalogues. | The current 0–35 scores are not the LLM being harsh; they are Arbeitnow returning German nursing jobs. Searching by term is what makes the corpus relevant, and it is the only model the Brazilian APIs offer. |
| Terms per source | The LLM extracts a **ranked list** of terms from the paragraph; the top **3–5** are searched per source, each 2–3 words. | Measured: `q=machine learning engineer` on Himalayas returns 2 934 coherent results. Stuffing "machine learning LLM Python agents internship" into one query collapses the result set — each extra word narrows. Several short queries beat one long one. |
| Deduplication | None added. The existing upsert handles it. | Ingest is already an upsert keyed by `(source, external_id)`. The same job arriving from three queries is one row; later arrivals only touch `last_seen_at`. A stage-1 decision that now pays off: we can be generous with queries without dirtying the database. |
| Re-extraction | Terms are re-extracted **only when the paragraph changes**, detected by hash. | The same `content_hash` trick ingest already uses for jobs. A scheduled daily run then spends no LLM quota on extraction, leaving it for scoring. |
| Scoring | **Every job is scored by embedding; only the top are explained by the LLM.** The prefilter stays. | The user asked for every job to be analysed. Embeddings are cheap and do score everything, so the ranked list is complete. The LLM is the expensive part and the user pays for it with their own key, so it runs only where it adds something: an explanation for a job that might actually be worth reading. |
| Run model | A search runs **in the background**; the page polls and renders as results arrive. | Scoring is not instant — a measured matching pass took 1 min 17 s over 1 456 candidates, and free LLM tiers rate-limit. Blocking the page on that would mean minutes of spinner. |
| Progress | Read from the existing **`Run.counters`**. | `candidates`, `evaluated`, `embedded`, `skipped_low`, `errors` are already written per run. The progress bar needs no new model. |
| Transport | **Polling every 2 s**, not SSE or WebSocket. | On localhost, for one user, polling is free and adds no dependency. Streaming would be more elegant and more fragile, with no difference the user could perceive. |
| Card ordering | Cards **reorder automatically** as scores arrive. No "refresh" button. | The user's explicit preference: they would rather watch it move than click. |
| UI language | **English and pt-BR**, default English, switchable. | §1.1. |
| UI text tone | The design system's content rules apply **to both languages**: sentence case, verbs in the infinitive, concrete numbers, errors that say what happened and what to do. | The tone rules are language-independent and good; only the "pt-BR only" clause is overridden. |
| Switching UI language | **Existing LLM explanations are left alone.** The interface switches immediately; explanations written earlier stay in the language they were written in, and new ones follow the current locale. | Re-scoring everything to translate it would spend the user's entire quota on a language toggle. A temporarily mixed screen is cheaper and honest. The UI must not imply the explanations will be retranslated. |
| Arbeitnow | **Stays in the code and in the generic contract test, but is off by default.** | It is the source of the German corpus that produced the 0–35 scores, and being catalogue-only it costs an embedding for every irrelevant job it dumps. It is also the project's only catalogue-only source, which is what proves the source contract still accepts both kinds — so it is disabled, not deleted. |
| Scheduler | **Off by default** for a fresh clone. One environment variable turns the daily run on. | The user described "open it, run it, look, close it". Spending someone's LLM quota on a schedule they never asked for is the wrong default, especially with the window closed. |
| What a run scores | The **whole active corpus** that has no match or a stale one — not only the jobs this run just fetched. | This is what "every job is analysed" means, and it is already `select_candidates`'s rule. It is only safe because sources are now searched by term and Arbeitnow is off: the corpus stays relevant instead of accumulating noise. |
| Completeness vs. the caps | The existing caps stay. A run **resumes where the last one stopped**, and the page states how many jobs are still unranked. | `max_embeddings_per_run=100`, `max_llm_evaluations_per_run=25` and the ~30k tokens/minute free tier are real. Removing the caps to finish in one pass would mean a twenty-minute first search or a 429 streak. Being visibly incomplete beats being slow and silent. |

## 3. Sources

### 3.1 Verified by live probe, not by documentation

Third-party documentation for these APIs is wrong in ways that matter. Every claim
below was checked against the live endpoint on 2026-10-22.

| Source | Key | Search parameter | Notes |
|---|---|---|---|
| **Himalayas** | none | **`q=`** | 123 545 jobs. **Third-party docs say `query=`; that is wrong** — `query=`, `search=` and `keyword=` all return the unfiltered catalogue (127 255), while `q=kubernetes` returns 5 000. Browse feed `/jobs/api` has cursor pagination (`nextCursor`, preferred; `offset` is deprecated). Search `/jobs/api/search` is 20 per page via `?page=`, no cursor. Remote-global, US-heavy: of 20 Python jobs, 1 accepted Brazil. |
| **Remotive** | none | `search=` | `https://remotive.com/api/remote-jobs`. Works, lower volume. |
| **Arbeitnow** | none | — | Already implemented. 300 per page, **no search parameter** — catalogue only. This is the source of the current irrelevant corpus, so it is **off by default** (§2). It stays registered and contract-tested: it is the only catalogue-only source, and therefore the only proof that the contract still accepts both kinds. |
| **Adzuna** | `app_id` + `app_key`, free signup | `what=` | `https://api.adzuna.com/v1/api/jobs/br/search/1`. Country code `br` is consistent across every third-party source that names it, with currency BRL. **Not verifiable without a key** — unauthenticated requests return a generic HTML error page identical to the one a bogus country returns. The implementer must confirm `br` and the free-tier quota with a real key before relying on it. |
| **Jooble** | free key | keyword in body | Covers Brazil. Sources disagree on GET vs POST and on the host (`jooble.org` vs `us.jooble.org`); confirm against the official docs after registering. |

### 3.2 Rejected, with reasons recorded so nobody re-proposes them

- **LinkedIn** — no public jobs API.
- **Gupy** — official API is OAuth partner access for ATS integration, not job search.
- **Programathor, Coodesh, Trampos** — no public API found.

### 3.3 Contract change

The source contract gains **search**. A source must expose which capability it has:
keyless or keyed, searchable or catalogue-only. Arbeitnow stays catalogue-only and
must keep working unchanged — the generic contract test in `tests/` runs against
every registered source and must still pass for it.

A source whose required credentials are absent **does not register**. This must be
observable: the API reports which sources are active and which are dormant for want
of a key, because the UI and the README both have to say so.

## 4. Components

```
src/jobscout/sources/himalayas.py     new, keyless, searchable
src/jobscout/sources/remotive.py      new, keyless, searchable
src/jobscout/sources/adzuna.py        new, keyed, searchable, Brazil
src/jobscout/sources/jooble.py        new, keyed, searchable, Brazil
src/jobscout/sources/base.py          + search capability, + credential availability
src/jobscout/matching/terms.py        new: paragraph -> ranked search terms (LLM)
src/jobscout/pipeline/search.py       new: the background run (terms -> fetch -> score)
src/jobscout/api/routers/search.py    new: start a run, read its progress
src/jobscout/api/routers/sources.py   new: which sources are active, which need a key
src/jobscout/api/routers/matches.py   + PATCH for status
src/jobscout/web/                     new: static page, CSS, JS, i18n dictionaries
src/jobscout/web/design/              the design system, moved from jobscout-design/
```

**The design system lives inside the package, not at the repo root.** Its own README
says to copy it to `design/`, and that is wrong here: anything served by StaticFiles
from outside `src/` is missing from a non-repo install. It ships as package data.

`sources` still performs no DB work. `matching/terms.py` has no HTTP and no sources —
it takes a string and returns terms. `pipeline/search.py` is the only composer.
`api` stays a thin shell. The existing dependency rule is unchanged.

## 5. Behaviour

### 5.1 A search run

1. The page POSTs the paragraph. The server stores it on `UserPreferences`, hashes it,
   and returns a run id **immediately**.
2. If the hash differs from the stored one, the LLM extracts a ranked term list and it
   is stored. If not, the stored terms are reused and no LLM call is made.
3. For each registered source, the top 3–5 terms are searched and the results upserted.
   **A source that fails does not fail the run** — this matches `ingest_job`'s existing
   rule, and stage 4 established that a run is ok when at least one unit of work
   succeeded, and not ok when all of them failed.
4. Jobs are embedded and scored. The candidate set is **every active job with no match
   or a stale one**, not only what this run fetched — `select_candidates`'s existing
   rule. Matches are committed **incrementally**, so the page can show them as they
   appear.
5. Counters are written to `Run` throughout, not only at the end.

**A run does not have to finish the corpus.** The caps (`max_embeddings_per_run`,
`max_llm_evaluations_per_run`) stop it long before a large backlog is exhausted, and
that is deliberate — see §2. The run records how many candidates remain, the next run
resumes from there, and the page says so in words rather than implying the ranking is
complete. The first search on a fresh install therefore returns a good partial ranking
in a reasonable time instead of a complete one in twenty minutes.

**Concurrency.** A second search request while one is in flight returns the run already
in progress. The run executes as an ad-hoc APScheduler job, reusing the executor that
already exists rather than adding a second concurrency model against the same SQLite
file. A user-initiated search is never skipped by the backoff; scheduled runs still are.

### 5.2 The page

Layout is `src/jobscout/web/design/DESIGN.md`'s main screen, the chosen mockup plus a detail
pane: header, full-width preference input, then a job-card list (~400 px) on the left
and a sticky detail panel on the right. Below 800 px it becomes one column and the
list and detail become separate views. Maximum width 1200 px.

- Cards are ordered by score and **reorder as new scores arrive**.
- Progress comes from `Run.counters`, polled every 2 s.
- **Which sources are active, and which would be unlocked by a free key, is stated on
  the page** — not buried in settings. This was an explicit requirement.
- A card can be saved, dismissed or marked applied.

### 5.3 Degradation

- No LLM key → the page says so plainly and the search does not start. This is the one
  hard requirement; everything else is optional.
- No source keys → keyless sources run; the page names what a key would add.
- A source errors or rate-limits → the other sources still produce results, and the
  failure is named in the run.
- No jobs clear the bar → the page says nothing matched and what to try, rather than
  showing an empty frame.

## 6. Amendments to the parent spec

- **§4 components:** add the modules in §4 above; remove Reflex.
- **§5:** the pipeline gains a term-extraction step before collection.
- **§7:** `Match` gains the status `applied`. `UserPreferences` gains the extracted
  terms and the paragraph hash.
- **Roadmap:** stage 6 keeps auth, Postgres/Docker; it loses the Reflex UI and i18n.

## 7. Out of scope

Multiple profiles per person (the data is already keyed by `user_id`, so this is a
table later, not a rewrite); a hosted demo (stage 7, and the user has not decided
whether it will exist); any shared or central database; e-mail changes; salary
normalisation across currencies; and per-source pagination beyond the first few pages.

## 8. Testing

No test touches the network, an LLM, or a real clock. Fixtures plus `respx`; the
existing fake models for LangChain.

- Each new source: one fixture-based test, plus the existing generic contract test.
- **A fixture captured from the live API**, not hand-written, so a shape change is
  caught rather than imagined.
- Term extraction: a fake LLM returns a known list; the paragraph hash suppresses the
  second extraction.
- A source without credentials does not register, and the run still succeeds.
- One source raising does not stop the others, and the run is still ok.
- Matches are visible before the run finishes.
- Both locales render; the default is English.

## 9. Done when

`uv run pytest` green, `mypy src` clean, ruff clean, CI green. And: a clone with only
an LLM key returns ranked tech jobs from the keyless sources, and adding an Adzuna key
adds Brazilian ones — both confirmed by actually doing it.

## 10. Calls made without the user, open to veto

- **`applied` joins `MATCH_STATUSES`**, and like `dismissed` it is terminal — staling
  never drags it back for re-evaluation. The design system specifies a "Candidatado"
  state; without it the UI asks for something the backend cannot store.
- **Dismissed and applied cards are hidden by default.** `list_matches` returns every
  scored row, so without this the user's "no" keeps reappearing on every search.
- **`jobscout-design/` moves to `src/jobscout/web/design/`**, not to the repo root as
  its README says — see §4. Its `CLAUDE.md` guidance is merged into the project's.
- **`tailwind.preset.js` is not used.** It is optional in the kit, and using it would
  reintroduce the frontend build this stage removed.
- **The design system's example error message cites LinkedIn**; the example changes
  platform, since LinkedIn is out.
- **i18n is a JSON dictionary per locale**, no framework.
- **Term extraction also fills the structured preference fields** (`titles`,
  `seniority`, `work_modes`, `regions`, `required_skills`, `excluded_keywords`), not
  just the term list. The user described the paragraph being taken apart into
  characteristics and technologies, and `filters.py` and `build_user_prompt()` already
  read those fields — leaving them empty would make the filter inert and strip the
  LLM prompt of its constraints. A changed paragraph stales the affected matches
  through the mechanism that already exists.
- **One page per term per source.** With four sources and up to five terms that is at
  most a few hundred jobs per run, which the caps can absorb.
- **A second search while one is running returns the live run** instead of starting or
  queuing another. Superseding would throw away work the user is watching.
- **The background run is an ad-hoc APScheduler job**, reusing the executor that
  already exists rather than introducing a second concurrency model beside it against
  the same SQLite file.
- **`RUN_JOBS` gains `"search"`**, with fetch-side counters alongside the match-side
  ones, because fetching is often the slow half and a progress bar that ignores it
  would sit at zero for most of the wait.
- **A user-initiated search is never refused by the backoff.** Stage 3 established
  that a wake must not be swallowed; a person clicking a button deserves at least as
  much. The backoff still governs scheduled runs.

## 11. Carried forward, deliberately not solved here

Adzuna and Jooble cannot be verified without keys. If the free tiers turn out to be
too small to be useful, that is a finding to record — **not** a reason to reach for
scraping. The user was explicit: if no legitimate source covers Brazil well enough,
a different approach gets designed later rather than the rule being bent now.

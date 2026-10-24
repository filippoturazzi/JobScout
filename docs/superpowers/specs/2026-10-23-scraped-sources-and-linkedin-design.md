# Scraped sources and LinkedIn: Design Spec

**Date:** 2026-10-23
**Status:** Draft, awaiting the user's approval
**Parent specs:** `docs/superpowers/specs/2026-09-19-jobscout-design.md`,
`docs/superpowers/specs/2026-10-22-stage-5-sources-and-dashboard-design.md`
**Reverses:** the stage 5 spec's §2 "Scraping — still forbidden", its §3.2 rejection of
LinkedIn, and its §11 "not a reason to reach for scraping"
**Plan affected:** `docs/superpowers/plans/2026-10-22-stage-5a-sources-and-search.md`
(Tasks 1, 2, 3, 5 and 6 are already committed; Task 4 and Tasks 7–8 are open)

## 1. Purpose and why now

Stage 5a shipped term-searched sources, term extraction from the profile paragraph, and
a search run that composes them. What it has to search is still thin: two keyless remote
boards, one keyed source the user has now rejected on price (Adzuna), and one keyed
source still to build (Jooble). None of them is where the jobs the user actually wants
are posted.

On 2026-10-23 the user decided: **LinkedIn is required**, collected through
[JobSpy](https://github.com/speedyapply/JobSpy), with a residential proxy as an option
rather than a requirement. The same decision retires the hosted demo — the project is an
open-source tool people run on their own machine, nothing more.

This reverses a rule written twice with the user's confirmation. The reversal is theirs,
made with the trade-offs stated: that JobSpy scrapes, that scraping violates LinkedIn's
and Indeed's terms of use, that scrapers break when the target's markup changes, and
that a residential proxy costs money. Recording it here is what keeps the repository
from contradicting itself.

## 2. The reversal

| Was | Now | Why |
|---|---|---|
| **Scraping forbidden.** No LinkedIn, no Gupy. (stage 5 spec §2) | **Scraping allowed, through JobSpy only.** LinkedIn, Indeed and Google Jobs register as sources. | The user's call: the jobs they want are on LinkedIn, and no legitimate API carries them. The rule was written to protect a portfolio project from an obvious objection; the user weighed that and chose coverage. Gupy stays out — not by rule now, but because JobSpy does not cover it. |
| Hosted demo in **stage 7** (quotas, BYOK) | **Dropped.** Self-hosting only. | The user: "a ideia é que seja só um projeto open source mesmo, acho que nem demo vai ter mais". It also removes the only place a proxy would have been mandatory: LinkedIn from a datacenter IP is blocked, so a hosted JobScout could not have collected it without the operator paying. |
| **Adzuna** unlocks Brazil with a free key (stage 5a Task 4) | **Dropped.** | The user found it is no longer free. Brazilian coverage now comes from LinkedIn, Indeed `br` and Google Jobs. |
| Sources are all **documented public APIs** | Two kinds: documented APIs **and** scraped boards, named as such | A contributor has to be able to tell which is which — one kind breaks when a server changes its contract, the other when a page changes its markup. |

## 3. Decisions

| Topic | Decision | Rationale |
|---|---|---|
| Collector | **JobSpy (`python-jobspy`, MIT)** is the only scraping path. No scraper written in this repo. | Keeping the scraping in a maintained upstream with 4 500 stars and pushes this week is the difference between a dependency and a liability. When LinkedIn changes, someone else fixes it. |
| Sites registered | **`linkedin`, `indeed`, `google`.** | Glassdoor and ZipRecruiter are US-centred; Bayt, Naukri, BDJobs and HelloWork cover markets that are not the user's. Registering a source nobody searches costs a contract test and a fixture for nothing. |
| Granularity | **One source file per site**, each calling `scrape_jobs(site_name=["<site>"], …)`. | The registry already reports status per source and the run already names failures per source. One combined "jobspy" source would collapse three failure modes into one and make `SOURCES=linkedin,remotive` impossible. The cost is losing JobSpy's internal concurrency across sites, which the search run does not need. |
| Default | **All three on by default**, no proxy, no key. | The user's call. It keeps the project's promise — clone, paste an LLM key, run — intact for the sites that tolerate it. |
| Proxy | **`JOBSPY_PROXIES`, operator config, empty by default.** When set, it is passed through to every JobSpy source. | Nobody needs a proxy to run JobScout from their own machine. Residential proxies are paid (roughly US$1–7/GB pay-as-you-go) and the free tiers on offer are datacenter IPs, which is exactly what LinkedIn blocks. A paid dependency must never sit in the default path of an open-source tool. |
| LinkedIn descriptions | **`fetch_description=True`.** The description arrives with the posting; there is no back-fill step and no `pipeline/descriptions.py`. | A reversal of an earlier call of mine, after reading upstream. JobSpy exposes **no way to fetch one posting's description**: `scrape_jobs()` is a search call, and the only per-job path is `LinkedInScraper._fetch_details()`, which is private and would break on any upstream release — the opposite of the reason JobSpy was chosen. Re-running a search with descriptions on would re-pay the search and hit the same per-job cost anyway, and parsing the posting URL in-repo is forbidden twice in this document. So the cost is paid up front and absorbed by searching less, not by deferring it. |
| Volume for scraped sources | **`jobspy_results_wanted=10`, `jobspy_max_terms=3`** (the keyless sources keep five), `hours_old=168`. | With descriptions on, every posting is a request: five terms × 25 results is ~125 LinkedIn requests per run, which is a block. Three terms × ten is ~30, and the LinkedIn scraper already sleeps a random 3–7 s between pages on its own. It also keeps a run's harvest near the existing caps instead of ten times over them. |
| The existing caps | **Unchanged** (`max_embeddings_per_run=100`, `max_llm_evaluations_per_run=25`), and `select_candidates` **gains an order**: newest `posted_at` first, nulls last. | Raising the caps spends the user's own LLM key, which is not mine to spend. Three scraped sources at 3 × 10, plus the keyless ones, lands near 100 jobs a run — inside what the caps can absorb. The ordering matters more than it looks: selection has no order today, so the 25 explanations the user pays for would go to whatever the database happened to return rather than to the freshest postings. |
| Google Jobs | Searched through **`google_search_term`**, the only parameter it filters on. | JobSpy's own documentation: `search_term` does not reach Google. Passing it would silently return an unfiltered feed. |
| Location | `pipeline/search.py` **starts populating `SearchQuery.locations` and `remote_only`** from the stored preferences (`regions`, `work_modes`). Indeed maps the **first recognised** region to `country_indeed` and falls back to `worldwide`, naming the unmapped value in the run's warnings. | A verified gap, not a detail: `SearchQuery.locations` has existed since stage 1 and **nothing has ever filled it** — `search.py` builds `SearchQuery(keywords=[term])` and no source reads the rest. Without this change the Brazilian coverage this document promises would silently never happen, because `country_indeed` would always be `worldwide`. Only the first region is used: searching every region × every term multiplies the block risk by the number of regions. Region stays a user preference in the database (commit 51520af deliberately stopped the extractor from inventing one), never env. |
| The same job from several sources | **A `fingerprint` column on `Job`**, from normalised title + company + location, written at ingest. A row whose fingerprint already exists updates `last_seen_at` and records the extra source in `raw`; it does not become a second row. | The user's call (§10). Google Jobs aggregates LinkedIn and Indeed, so one vacancy arrives under three `(source, external_id)` keys and the stage-1 upsert will not merge them — three embeddings, three cards and up to three LLM explanations paid for with the user's own key. Location is in the key deliberately: without it, one company posting the same title in São Paulo, Rio and Lisbon would collapse three real vacancies into one. This **amends the ingest invariant** named in `CLAUDE.md`: the upsert is still keyed on `(source, external_id)`, with a fingerprint merge in front of it. |
| Failure | A site that blocks, rate-limits or changes shape **fails that source only.** The run is ok if any source produced jobs, and the failure is named in `Run.counters.errors`. | Already the rule the stage 5a plan's review focus #2 and #3 demand. Scraped sources make it routine rather than exceptional. |
| Honesty in the README | The README **states plainly** that LinkedIn, Indeed and Google are collected by scraping through JobSpy, that this violates those sites' terms of use, that these sources can break at any time, and that a proxy is optional and paid. | Someone who clones this runs the scraping from their own IP. They get to know that before the first run, not from an issue thread. |

## 4. Sources after this change

| Source | Kind | Credential | Default | Search |
|---|---|---|---|---|
| `himalayas` | documented API | none | on | `q=` |
| `remotive` | documented API | none | on | `search=` |
| `jooble` | documented API | free key | on when keyed | keyword in body |
| `linkedin` | scraped, JobSpy | none; proxy optional | **on** | `search_term` |
| `indeed` | scraped, JobSpy | none; proxy optional | **on** | `search_term` + `country_indeed` |
| `google` | scraped, JobSpy | none; proxy optional | **on** | `google_search_term` |
| `arbeitnow` | documented API | none | off | none (catalogue) |
| `adzuna` | — | — | **removed** | — |

`Settings.sources` becomes `himalayas,remotive,jooble,linkedin,indeed,google`.

**A verified latent fault to fix in the same work:** the declared default is
`"himalayas,remotive,adzuna,jooble"` (`config.py:19`), and `build_sources` raises
`ValueError: Unknown source(s) in SOURCES: adzuna, jooble` on it today — only the local
`.env` (`SOURCES=arbeitnow`) hides it, and `.env.example` ships that same stale pin.
Every name in the default must exist in `SOURCE_FACTORIES`, and `.env.example` must stop
pinning `arbeitnow`. If Jooble is deferred for want of a key (§10), it leaves the
default string too.

## 5. Components

```
src/jobscout/sources/jobspy_base.py   new, shared adapter: scrape_jobs() -> list[RawJob]
src/jobscout/sources/linkedin.py      new, scraped, searchable
src/jobscout/sources/indeed.py        new, scraped, searchable
src/jobscout/sources/google.py        new, scraped, searchable
src/jobscout/sources/jooble.py        new, keyed, searchable (stage 5a Task 4, unchanged)
src/jobscout/sources/adzuna.py        never written; dropped
src/jobscout/pipeline/search.py       modified: fills locations and remote_only,
                                      fewer terms for scraped sources
src/jobscout/pipeline/matching.py     modified: select_candidates orders by posted_at
src/jobscout/models/job.py            modified: fingerprint column, indexed
src/jobscout/pipeline/ingest.py       modified: fingerprint merge before the upsert
README.md                             the ALTER TABLE line and the back-fill snippet,
                                      beside the ones at README.md:88-90
src/jobscout/config.py                JOBSPY_PROXIES, jobspy_results_wanted,
                                      jobspy_max_terms, jobspy_hours_old
```

Dependency added: **`python-jobspy` as a hard dependency, not an extra.** It brings
pandas, and it performs its own HTTP outside the project's `httpx` client — the first
dependency to do either, which is why §7 exists. An extra (`jobscout[scraped]`) would
keep the base install light, but then the default `SOURCES` would name three sources
that are not installed, and "clone, paste an LLM key, run" would stop being true for
the sources the user cares most about. `mypy` gets an `ignore_missing_imports` override
for `jobspy.*`, since CI runs it in strict mode.

## 6. Behaviour

A search run is unchanged in shape: terms from the paragraph, then each source searched
for the top 3–5 terms, then scoring over the whole active corpus. The scraped sources
join it as ordinary `JobSource` implementations — the contract in `sources/base.py` is
already synchronous, which is what `scrape_jobs()` is, so no threading or async bridge
is introduced.

What is new:

- A JobSpy source returns a pandas `DataFrame`; the adapter converts it to `RawJob`
  rows and drops nothing based on the query, as the contract requires.
- `external_id` comes from JobSpy's own `id`. Verified against upstream `model.py`:
  `JobPost.id` is `str | None`, so it cannot be trusted alone — the adapter falls back
  to a hash of `job_url`, which `JobPost` does require. A row missing `title` or
  `job_url` is skipped and named in the run's errors, as review focus #1 requires.
  `JobPost.company` is also optional while `RawJob.company` is not; a missing company
  maps to an empty string rather than costing the row.
- **A blocked site does not raise.** Verified in upstream `scrape_jobs()`: each site is
  scraped in a thread, its exception is captured, and the failure is reported as
  `jobs_df.attrs["errors"]` (with `attrs["warnings"]` beside it) while the call returns
  normally — an empty DataFrame. The adapter must read `attrs` and raise, or the run
  would record "LinkedIn returned 0 jobs, no errors" every time LinkedIn blocks it,
  which is the one failure this stage has to report honestly.
- Every scraped row carries a description at ingest, so neither `select_candidates` nor
  the generic contract test in `tests/` has to change. An earlier draft of this document
  claimed `select_candidates` already skips description-less rows: **it does not** — it
  filters on `is_active`, match status and the preference filter, and would have
  embedded and scored empty documents. With descriptions fetched at search time the
  problem is gone rather than handled, which is the better outcome but worth recording,
  because anyone who later turns `fetch_description` off reopens it.
- `pipeline/search.py` gives the scraped sources three terms and the keyless ones five,
  and passes the stored `regions`/`work_modes` through `SearchQuery`.
- Ingest computes the fingerprint before the upsert. A new fingerprint becomes a row as
  today. An existing one touches `last_seen_at`, appends the second source's name and
  URL under a `duplicates` key in `raw`, and stops — it never overwrites the first
  source's payload, because `pipeline/repair.py` re-renders the description from it. The
  first source to arrive wins, which with `SOURCES` ordered as in §4 means LinkedIn
  before Indeed before Google. Running ingest twice over the same data stays a no-op
  besides `last_seen_at`.
- Existing rows have no fingerprint until their source lists them again: ingest computes it
  on every refresh, and the normalisation is Python-side, so there is no SQL back-fill. A
  null fingerprint never merges, so nothing changes for a row until then; a row whose source
  never lists it again keeps a null fingerprint and never merges. The merge fires only
  across sources (`twin.source != raw.source`), so a same-source repost stays its own row.
- A 429 or a block mid-fetch keeps what was already fetched, abandons the remaining
  terms for that source, and says so in the run. Review focus #3, now the common case.

## 7. Testing

The project's rule is `respx` plus fixtures captured from the live API. **JobSpy makes
its own HTTP requests inside its own client, so `respx` cannot intercept them.** For the
three scraped sources only, the boundary moves one level out: the test patches
`scrape_jobs` and feeds it a recorded result captured from a real call, stored as a
fixture like any other. Every other rule holds — no network, no LLM, no real clock — and
the generic contract test still runs against all three.

This is an exception, written down so the next contributor reads it as a decision rather
than as sloppiness.

## 8. Documentation that must change in the same work

The repository currently asserts the opposite of this document in four places:

- `CLAUDE.md` — the "never scraping" claim in *What the project is*, and the roadmap's
  stage 7.
- `AGENTS.md` — the same two, duplicated for Codex.
- `docs/superpowers/specs/2026-10-22-stage-5-sources-and-dashboard-design.md` — §2
  Scraping, §3.2 LinkedIn, §11, and the Adzuna rows in §3.1 and §9.
- `README.md` — the source list, the honesty paragraph from §3, and the `ALTER TABLE`
  plus index lines for the fingerprint column (it fills itself on refresh; no back-fill), beside the ones at `README.md:88-90`.

The stage 5a plan's Task 4 shrinks to Jooble alone and blocks on the key (§10); three
tasks are added (the shared JobSpy adapter and its three sources, the fingerprint
column with its migration and back-fill, and the `SearchQuery`/ordering changes in
`pipeline/`); Tasks 7 and 8 stand.

## 9. Goals, non-goals, anti-goals

**Goals.** LinkedIn, Indeed and Google jobs in the corpus, through the existing source
contract, free to run and with no proxy required. Brazilian coverage as a consequence
rather than as a separate keyed tier.

**Non-goals.** A hosted demo. Bundling or recommending a proxy provider. The keyless ATS
boards (Greenhouse, Ashby — measured at QuintoAndar 108, Stone 372, Nubank 97), which
the user deferred to the next stage. Glassdoor, ZipRecruiter, Bayt, Naukri, BDJobs,
HelloWork. Writing any scraper in this repository.

**Anti-goals.** A clone that fails on first run because it lacks a proxy or a paid key —
if LinkedIn's block rate makes the default unusable, LinkedIn becomes opt-in and the
project does not acquire a paid dependency. A README that lets someone run a scraper
without knowing it is one. A second concurrency model: JobSpy runs inside the existing
synchronous `fetch`.

## 10. Answered by the user, 2026-10-23

**The same job from three sources.** Google Jobs aggregates Indeed and LinkedIn
postings, so one vacancy can arrive as three rows with three different
`(source, external_id)` keys. The existing upsert will not merge them: it is keyed
exactly on that pair, by a stage-1 decision. Each copy would then be embedded, counted
in the progress bar, possibly explained by the LLM — the one cost the user pays with
their own key — and shown as three cards.

**Decided: the `fingerprint` column, with location in the key** — normalised title +
company + location, written at ingest, merging as §3 and §6 describe. The user chose
this over accepting duplicates, and chose location in the key over the simpler
title + company, so that one company advertising the same role in São Paulo, Rio and
Lisbon stays three rows.

The cost is higher than a column suggests, and the plan must carry it as its own task:
the project has **no Alembic** — `db.py` calls `SQLModel.metadata.create_all`, and
earlier columns were added by hand-written `ALTER TABLE` lines documented at
`README.md:88-90`, against a live `jobscout.db` that already holds the user's data. So
this means an `ALTER TABLE`, an index, a back-fill of existing rows, a README entry
beside the existing ones, and the amendment to the ingest invariant recorded in §3.

**Decided: Jooble stays, and the user registers the key.** It remains in §4's default
source string. The implementer cannot finish it before the key exists, because the
stage-5a plan forbids hand-written fixtures and requires a response captured from the
live API — so the Jooble task blocks on the key arriving and must not be faked around.

**Decided: the user runs the live check.** The implementer prepares the command and
says what to look for; the user runs it from their own connection and reports what came
back. Nothing in this work scrapes LinkedIn or Indeed from the user's IP without them
starting it. If a proxy-less run is blocked **twice in a row**, §12's fallback applies:
LinkedIn ships opt-in, the README says why, and the finding is recorded rather than
answered with a paid proxy in the default path.

## 11. Calls made without the user, open to veto

- The three sites registered, and the five not registered (§3).
- One source file per site rather than one combined source (§3).
- `fetch_description=True` and no back-fill module, after finding JobSpy has no public
  per-job description call (§3).
- Defaults `jobspy_results_wanted=10`, `jobspy_max_terms=3`, `hours_old=168`; the
  existing caps untouched; `select_candidates` ordered newest first (§3).
- `pipeline/search.py` populating `SearchQuery` from the stored preferences, and Indeed
  using only the first recognised region, `worldwide` when there is none (§3).
- `python-jobspy` as a hard dependency with a mypy override, not an extra (§5).
- `external_id` falling back to a hash of `job_url` when JobSpy gives no `id`, and a
  missing `company` mapping to an empty string instead of dropping the row (§6).
- Reading `jobs_df.attrs["errors"]` and raising from the source, so a silently blocked
  site is reported rather than looking like an empty result (§6).
- Patching `scrape_jobs` in tests instead of `respx` (§7).
- `sources/jobspy_base.py` as a shared adapter rather than three copies of the mapping.

## 12. Done when

`uv run pytest` green, `uv run mypy src` clean, ruff check and format clean, CI green.
And, confirmed by actually running it — the user runs the live check (§10): a fresh
clone with only an LLM key returns ranked LinkedIn, Indeed, Google, Himalayas and
Remotive jobs for a Brazilian profile paragraph, with no proxy configured; every scraped
row arrives with a description; and a blocked site leaves the run ok with that site
named in its errors, read from `attrs`, rather than silently reporting zero jobs.

If LinkedIn blocks a proxy-less run **twice in a row** from a residential IP, the
anti-goal applies: LinkedIn ships opt-in, the README says why, and the finding is
recorded rather than worked around with a paid proxy in the default path.

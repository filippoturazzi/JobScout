# Idea: a conversational interface with saved sessions

**Date:** 2026-11-06
**Status:** Idea only, not designed or approved. It has to go through a design before it
is built. If approved, it replaces the page described in
`docs/superpowers/specs/2026-10-22-stage-5-sources-and-dashboard-design.md` §5.2, which
has not been built yet.

## The idea, as the user described it

- The interface is very clean, with little information on screen. In the middle there is
  one text field, in the same style as ChatGPT, Claude or Gemini.
- The user writes a paragraph about the job they want. That opens a session: a
  conversation in the same style as an AI assistant.
- The app asks about whatever the first paragraph left out. For example: "you did not say
  whether you want remote, on-site, hybrid, or don't mind".
- These questions are answered with option buttons, not by typing.
- Once the context is complete, it searches every job and shows the results.
- The session stays saved in a left-hand menu, like a conversation.
- A session can be automated later: scheduled to search for all jobs at a set time, for
  example once a day.
- The user can create a new session for another job, another role they want, or another
  person they know.

The goal behind it: finish the project, put it in the portfolio, and start using it.

## How it meets the code today (notes from reading the code, not user decisions)

**Already there and reusable**

- `pipeline.search.run_search` does the search itself, with progress written to
  `Run.counters`; `POST /search` and `GET /search/{run_id}` expose it.
- `matching.terms.extract_profile` already reads the paragraph with an LLM, and is the
  natural starting point for working out what the paragraph left unsaid.
- `Job` rows are shared, so several sessions can reuse one collected corpus.
- `scheduler.search_job` already runs a search as a background job.

**What the idea changes**

- **One profile per user becomes many.** `UserPreferences.user_id` is unique and `Match`
  is unique on `(job_id, user_id)`, so today a user has one profile and one verdict per
  job. Sessions need their own preferences and their own matches. Spec §7 of the stage 5
  design listed "multiple profiles per person" as out of scope, so this reopens it.
- **Sessions and messages need storage.** Nothing stores a conversation today, and `Run`
  has no link to a session.
- **The questions fit a rule already in the code.** `matching.terms` deliberately never
  extracts `work_modes` or `regions`, because a guessed hard filter can hide the best
  match. An explicit button answer is the user's own choice, so it can fill those fields
  safely, and "don't mind" leaves them empty.
- **LangGraph stays out unless the user reopens it.** The project rule limits LangGraph to
  the per-job matching graph, so the conversation would be plain Python and LLM calls.
- **Scheduling per session is new.** The scheduler has global intervals, and scheduled
  ingest has no search terms. Several scheduled sessions would also share one LLM budget.
- **The layout and design system need revisiting.** `jobscout-design/DESIGN.md` describes a
  full-width input above a job list and detail panel. It would need a conversation screen
  and a sidebar. The design kit is also still untracked in git.

## Decided by the user on 2026-11-06

- **A session for another person is only a separate search.** The owner runs it and shows
  that person a screenshot or the results in person. That person never opens the app, so
  sessions need no extra users.
- **Everyone runs their own copy.** The project is fully open source: download it, add
  your own LLM key, and run it on your computer. No demo and no hosted version.
- **E-mail stays off for now,** and may be removed later.
- **Screens are designed in pen.dev first.** Claude helps write the prompt for each screen,
  the user runs it in pen.dev, and work continues from what is on the canvas.
- **Whether login is needed is still to be confirmed.** The user doubts it. The server
  already binds to `127.0.0.1` by default, so a local copy is not exposed to the network.

## Open questions

- Does the first version include scheduling, or does it come after?
- After the first search, can the user keep talking to refine the session?

## The questions to ask (approved by the user on 2026-11-06, five at most)

Each question is asked only when the paragraph did not already answer it.

| Question | Options | What it does in the engine today |
|---|---|---|
| Role, only if none can be identified | Suggestions from the paragraph, or typed | Drives `search_terms`, so it decides what is fetched at all |
| Seniority | Intern, junior, mid, senior, don't mind | Reaches the embedding and the LLM prompt; only `excluded_keywords` removes jobs |
| Work mode | Remote, hybrid, on-site, don't mind | Hard filter, and remote-only narrows LinkedIn and Indeed |
| Location, depends on work mode | Countries, a city when hybrid or on-site, don't mind | Hard filter for non-remote jobs, and the LinkedIn and Indeed search location |
| Main skills, if the paragraph names none | Suggested from the role, multi-select | Reaches the prompt; `matched_skills` only counts what the profile shows |

Left out of the questions: minimum salary, contract type, English level. They still reach
the LLM when written in the paragraph, because `profile_summary` goes into the prompt as is.

### Engine gaps fixed on 2026-11-06 (branch `engine-location-and-work-mode`)

- A remote job that names only other places now fails the region filter. With no location, or
  one naming no country, it stays in, because hiding a job takes evidence.
- Hybrid and on-site are told apart when the posting says which it is. If it does not say, it
  stays a candidate for both.
- A remote-only board is not searched for someone who refuses remote, and the run says so.
- Countries are recognised worldwide, plus areas such as Europe and LATAM. LinkedIn and Indeed
  search every chosen country within their request budget, and a country left out is named in
  the run. "Abroad" is stored as `regions` empty and the home country in `excluded_regions`.
- The default match listing hides jobs the current preferences no longer select.

**Still waits for the conversation:** extraction now reports `stated_work_modes` and
`stated_regions`, but nothing filters on them until the user confirms them on screen. The
confirmed values go to `work_modes` and `regions` through `PUT /preferences`.

**Known limits:** Indeed has no worldwide search, so "abroad" with no country does not reach
it. Indeed has no site for some countries, Turkey included. Most non-remote postings do not
state a work mode (30 of 34 in the local database on 2026-11-06).

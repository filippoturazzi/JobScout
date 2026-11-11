# JobScout

Open-source AI agent that continuously searches public job-board APIs (and, for
LinkedIn and Indeed, scrapes them; see Job sources) and matches
postings against **your** profile — with an LLM explaining every score.

> Status: in development. Collection, LLM matching, the scheduler and e-mail digests (stages 0–4) work, as do
> stage 5's sources, saved searches and the conversational web page. Stage 6 adds Postgres and a Docker setup to
> run it 24 hours a day on a server.
> See `docs/superpowers/specs/2026-09-19-jobscout-design.md` for the full design and roadmap.

## Quick start

```bash
uv sync --all-groups
cp .env.example .env               # optional; defaults work out of the box
uv run jobscout fetch              # pull jobs from enabled sources into ./jobscout.db
uv run jobscout jobs               # jobs that pass the latest search's preferences (newest first)
uv run jobscout jobs --all         # every active job, ignoring preferences
uv run jobscout searches           # your saved searches, most recently used first
uv run jobscout serve              # API + Swagger UI at http://127.0.0.1:8000/docs
```

The search is the main way in. A search is a saved profile: you write a paragraph about
yourself, the model reads it once into search terms, and a short conversation (answered through
the API, soon the page) settles what it left open, such as regions and work modes. Running it
searches every source with those terms, scores what came back and keeps the ranking. It needs
an LLM key in `.env`.

```bash
curl -X POST http://127.0.0.1:8000/searches -H "Content-Type: application/json" -d '{"paragraph": "<a paragraph about you>"}'
curl -X POST http://127.0.0.1:8000/searches/1/run      # after answering its questions
uv run jobscout search             # the same run in the foreground, on the latest search
```

`search`, `match`, `matches` and `jobs` act on the latest search; `--search ID` picks another
(ids are in `jobscout searches`). With no search yet they say how to start one.

`serve` listens on `127.0.0.1` only, so nothing on your machine is reachable from the network.
The page has no login and spends your LLM key: change `API_HOST` only if you know you want
that, and prefer one of the options in [Run with Docker on a VPS](#run-with-docker-on-a-vps).

## Run with Docker on a VPS

The Docker setup runs JobScout 24 hours a day: the API, the page and the scheduler in one
container, Postgres in another, both restarting on failure and on boot. It publishes the page
on the server's `127.0.0.1:8000` only; the next section is how you reach it from your phone.

You need a Linux server with Docker and the compose plugin.

```bash
git clone https://github.com/filippoturazzi/JobScout.git && cd JobScout
cp .env.example .env
# edit .env: LLM_API_KEY, GOOGLE_API_KEY, POSTGRES_PASSWORD (openssl rand -hex 24), TZ
docker compose up -d
docker compose logs -f app         # Ctrl+C stops following, not the app
```

`docker compose up -d` pulls the published image; `docker compose up -d --build` builds it from
your checkout instead. Compose sets `DATABASE_URL` (its own Postgres) and `SCHEDULER_ENABLED=true`
itself, whatever `.env` says. Set `TZ` (for example `America/Sao_Paulo`): the daily digest hour
is local time, and a container is UTC otherwise.

### Open it from anywhere: Tailscale

[Tailscale](https://tailscale.com) puts the server and your own devices on one private network.
The page then opens from your phone or laptop anywhere, and from nowhere else. No domain, no
open port.

1. On the server: `curl -fsSL https://tailscale.com/install.sh | sh`, then `sudo tailscale up`.
2. Install the Tailscale app on your phone and computer and sign in with the same account.
3. On the server: `sudo tailscale serve --bg 8000`. It prints the address, of the form
   `https://<server-name>.<tailnet>.ts.net`, with HTTPS already set up.

### Other ways in

- **SSH tunnel**, for an occasional look from a computer: `ssh -L 8000:127.0.0.1:8000 user@server`,
  then open `http://127.0.0.1:8000` locally.
- **A public address with Caddy.** Point a domain at the server, install
  [Caddy](https://caddyserver.com), make a password hash with `caddy hash-password`, and use this
  `Caddyfile`; Caddy gets the HTTPS certificate on its own:

  ```
  jobs.example.com {
      basic_auth {
          me <hash from caddy hash-password>
      }
      reverse_proxy 127.0.0.1:8000
  }
  ```

  Anyone with that password can run searches and spend your LLM key, so make it a long one.

### Keeping it running

```bash
git pull && docker compose pull && docker compose up -d            # update
docker compose exec -T db pg_dump -U jobscout jobscout > jobscout-$(date +%F).sql   # back up
docker compose exec -T db psql -U jobscout jobscout < jobscout-2026-11-11.sql      # restore, into an empty database
```

The data lives in the `pgdata` volume: `docker compose down` keeps it, `docker compose down -v`
deletes it. The schema is created at startup and there is no migration tool yet, so a future
release that changes the schema will come with upgrade instructions for Postgres installs.

## Using the page

```bash
uv run jobscout serve
```

Open <http://127.0.0.1:8000>. Describe the job you want in a paragraph; the page reads it
and asks a few quick questions (role level, work mode, location, skills), then runs the
search across the enabled sources and scores what it finds with your LLM (set a provider
key in `.env` first). The results list shows each posting with its score; open one for the
reasoning, matched and missing skills and red flags, then save it, mark it applied or
dismiss it. **My jobs** gathers your jobs across every search, under the tabs All, Saved
and Applied; a dismissed job leaves every tab.
**Settings** shows the model and sources and switches the theme (dark by default) and the
language (English or pt-BR).

To try the page without a key or network, build a demo database and serve it:

```bash
uv run python scripts/seed_demo.py demo.db
DATABASE_URL=sqlite:///demo.db uv run jobscout serve              # bash
$env:DATABASE_URL = "sqlite:///demo.db"; uv run jobscout serve    # PowerShell
```

The page is plain HTML, CSS and ES modules under `src/jobscout/web/` (no build step); its
pure modules are tested with `node --test tests/web/*.test.js`.

## Matching (AI)

```bash
cp .env.example .env          # set LLM_API_KEY and GOOGLE_API_KEY
uv run jobscout match --dry-run   # ranked candidates, no LLM call (still embeds)
uv run jobscout match             # score them (bounded by MAX_LLM_EVALUATIONS_PER_RUN)
uv run jobscout matches --min-score 70
```

Two keys go in `.env`. `LLM_API_KEY` drives the chat model and can come from any supported
provider (Groq, DeepSeek, Google, OpenAI or Anthropic): JobScout recognises the provider from
the key's prefix and picks a cheap default model, so there is nothing else to set. Groq and
DeepSeek are the cheapest way to search every day; Gemini's free chat tier allows only about
20 requests a day. `GOOGLE_API_KEY` drives the embeddings (Gemini, free tier, bounded per
minute rather than per day), because most chat providers have no embeddings; a Google
`LLM_API_KEY` serves both. `.env.example` lists the prefixes, default models and prices, and
the optional `LLM_PROVIDER`, `LLM_MODEL` and `EMBEDDING_PROVIDER` overrides.

Each match carries a 0–100 score, a written justification, matched and missing skills, and
red flags. A cosine prefilter over cached embeddings decides what is worth an LLM call, so a
run costs a bounded number of requests. `--dry-run` makes no LLM call, but it still embeds
up to `MAX_EMBEDDINGS_PER_RUN` jobs (100 by default, sized to the Gemini free tier's
per-minute token budget) that have no cached vector yet, so it does spend
embedding quota. A real run ends with a summary line whose `pending=` counter is how many
candidates are still waiting for a vector — run `jobscout match` again to score the rest.
Without a provider key, everything except matching still works.

## Running continuously

The scheduler is **off by default**. Set `SCHEDULER_ENABLED=true` in `.env` and `jobscout
serve` runs it inside the API process, with these jobs: ingest (cheap HTTP) every
`INGEST_INTERVAL_MINUTES` (default 60) and matching (spends LLM and embedding quota) every
`MATCH_INTERVAL_MINUTES` (default 15), plus the digest below. The CLI always stays manual.
Scheduled ingest has no search terms, so it never reaches the scraped sources; only a search
does, and a search is always started by you (`POST /searches/{id}/run` runs even with the scheduler off). A failing
matching job backs off exponentially, capped by `MAX_BACKOFF_TICKS`; ingest does not back
off, since it is cheap keyless HTTP with no quota to protect. `GET /runs` lists what each run
did and whether it succeeded.

A change to a search's preferences scores nothing by itself: it marks the affected matches
stale. They are re-scored by the next run of that search, or by the scheduler's matching job on
its interval, search by search. With `SCHEDULER_ENABLED=false` they stay `stale` until you run
the search again or `jobscout match`. Scheduled ingest has no search terms, so what it collects
does not feed any search's scoring: a search scores only what it fetched itself, and a search is
run from the page (today `POST /searches/{id}/run`) or with `jobscout search`.

## Notifications

JobScout can e-mail you a daily digest of good matches. Set the `SMTP_*` settings and
`DIGEST_HOUR` in the environment (they are documented, commented out, in `.env.example`),
then set your address as the `notify_email` preference of a search; it is a user preference,
not operator config. The page will set it; until then it has no API route.

The digest is a scheduler job. It sends at most one message a day per user, at or after
`DIGEST_HOUR` in the server's local time, with at most 20 matches per message. That local
time is the process's timezone, so set `TZ` (for example `TZ=America/Sao_Paulo`) wherever the
default is not what you want — a container usually runs on UTC, which would silently turn
`DIGEST_HOUR=9` into 06:00 in UTC-3. Nothing is sent when no match clears your
`min_score_to_notify`; dismissed matches and inactive jobs are skipped. Each match is
announced once: it is stamped with `notified_at`, so re-scoring it later does not announce
it again. If a send fails, nothing is marked and the next firing retries.
`GET /runs?job=digest` shows what each digest run did.

E-mail needs both `SMTP_HOST` and `SMTP_FROM`; if either is unset it is disabled, silently
(no `Run` row, only an INFO log line), and everything else keeps working. The digest runs only
inside the scheduler, so it never fires from the CLI alone or with `SCHEDULER_ENABLED=false`.

### Upgrading an existing database

Stage 4 adds columns to tables that already exist, and `create_all` only creates missing
tables, so an install created before stage 4 fails with "no such column" until you run these
statements once:

```sql
ALTER TABLE "match" ADD COLUMN notified_at DATETIME;
CREATE INDEX ix_match_notified_at ON "match" (notified_at);
ALTER TABLE user_preferences ADD COLUMN notify_email VARCHAR;
```

The index is not optional: every digest selection filters on `notified_at`, so skipping the
`CREATE INDEX` leaves the install correct but progressively slower. A fresh database needs
none of this.

The profile search (stage 5) adds three columns: the search terms extracted from your profile
paragraph, the hash that decides when to extract them again, and the user a search run
belongs to. Without them `jobscout serve` stops at startup with `no such column:
user_preferences.search_terms`:

```sql
ALTER TABLE user_preferences ADD COLUMN search_terms JSON NOT NULL DEFAULT '[]';
ALTER TABLE user_preferences ADD COLUMN profile_hash VARCHAR;
ALTER TABLE run ADD COLUMN user_id INTEGER;
CREATE INDEX ix_run_user_id ON run (user_id);
```

Empty terms and no hash just mean the next search extracts them from the paragraph.

The scraped sources add one more column, `fingerprint` (normalised title + company + city),
which is how one vacancy arriving from several sources becomes one row:

```sql
ALTER TABLE job ADD COLUMN fingerprint VARCHAR;
CREATE INDEX ix_job_fingerprint ON job (fingerprint);
```

The index is not optional here either: every new posting is looked up by `fingerprint`, so
skipping the `CREATE INDEX` makes each ingest scan the whole `job` table. There is nothing to
back-fill by hand, and no SQL could do it, since the normalisation runs in Python: existing
rows start with a NULL fingerprint, which never merges with anything, and each one gets its
fingerprint the next time its source lists it again. From then on it can absorb another
source's copy of the same vacancy. A row whose source no longer lists it keeps a NULL
fingerprint forever and never merges. Only a different source merges: a repost from the
same source under a new id stays its own row. A posting with no company has no fingerprint and
never merges, since its title alone would collapse different vacancies.

What the merge is for, honestly: it was built for Google Jobs, which aggregates LinkedIn and
Indeed, so one vacancy would have arrived three times. Google was dropped (no capture returned
postings). Between LinkedIn and Indeed it fires only when title, company and city agree
exactly, and their formats rarely do: LinkedIn writes `Greater São Paulo Area` where Indeed
writes `São Paulo, SP, Brazil`, and LinkedIn titles carry suffixes Indeed's do not. The key is
kept strict on purpose, because a loose one would silently delete real vacancies; the column is
infrastructure for the next aggregating source more than a feature today.

Ruling a country out (how "abroad" is stored: `regions` empty, the home country in
`excluded_regions`) adds one more column:

```sql
ALTER TABLE user_preferences ADD COLUMN excluded_regions JSON NOT NULL DEFAULT '[]';
```

#### Saved searches (2026-11-07)

This version reorganises preferences into saved searches: your preferences become your first
search, and matches belong to a search instead of directly to you. The `ALTER TABLE` lines
above do not cover this, and every command stops with a message until the database is
converted. Run, once:

```bash
uv run jobscout upgrade-db
```

It copies the SQLite file to `<file>.bak-YYYYMMDD-HHMMSS` first, then converts it in one
transaction, keeping every match with its id and status (applied and dismissed included); if
anything fails, nothing changes. It never overwrites an earlier backup. Postgres is not supported
by the upgrade, which refuses it (no released install uses it).
Stored `titles` become the first search terms, and the next "Search jobs" saves them as terms only
(`titles` empty), since the conversation owns the preferences now.
The same command also adds the `run.sources` column (per-source progress of a search run) to a database that already has saved searches.

## API

| Method | Path | Description |
|--------|------|-------------|
| GET    | `/health` | Liveness |
| GET    | `/status` | LLM key found (never the key), provider, models, sources, the running search, your locale |
| PUT    | `/me/locale` | `{"locale": "en" \| "pt-BR"}` |
| GET    | `/searches` | Your searches, most recently used first |
| POST   | `/searches` | `{"paragraph": ...}`: a new search, read once; the answer carries the first question |
| GET    | `/searches/{id}` | The search and its conversation |
| DELETE | `/searches/{id}` | Remove it with its matches; the jobs stay |
| POST   | `/searches/{id}/answers` | Answer one of its questions |
| POST   | `/searches/{id}/refinements` | `{"text": ...}`: add to the paragraph and read it again; never runs the search |
| POST   | `/searches/{id}/reread` | Try the reading again after it failed |
| POST   | `/searches/{id}/run` | Confirm the conversation, then fetch and score in the background; returns `{"run_id": ...}`; refused while another search runs |
| POST   | `/searches/{id}/rank` | Score what the search already holds, calling no source |
| GET    | `/searches/{id}/runs/{run_id}` | That run's progress: its counters are written while it runs |
| GET    | `/searches/{id}/matches` | Scored matches, best first (`?min_score=`, `?status=`, `?limit=`); dismissed and applied ones only with `?status=` |
| PATCH  | `/matches/{id}` | `{"status": "saved" \| "dismissed" \| "applied"}`; dismissed and applied are never re-scored |
| GET    | `/my-jobs` | Jobs you saved or applied for, across searches |
| GET    | `/jobs` | Active jobs passing a search's preferences (`?search_id=`, default the latest; `?all=true` ignores them; `?limit=`) |
| GET    | `/sources` | Every enabled source, and for a dormant one what would wake it |
| GET    | `/runs` | Run history (ingest, match, digest, search), newest first |

## Development

```bash
uv run pytest                      # unit tests, no network
uv run pytest -m integration       # opt-in tests against real APIs
uv run pytest tests/sources/test_arbeitnow.py::test_fetch_maps_fields   # single test
uv run ruff check . && uv run ruff format .
uv run mypy src               # static typing (strict, src only)
node --test tests/web/*.test.js   # the page's JS modules (Node 22, no packages)
```

Adding a job source: implement `JobSource` in `src/jobscout/sources/<name>.py` returning `RawJob`s,
register it in `sources/registry.py`, add `tests/fixtures/<name>_sample.json` and one line in
`tests/sources/test_contract.py`. The contract test does the rest.

## Job sources

| Source | Kind | Credential | On by default | Notes |
|---|---|---|---|---|
| `himalayas` | documented API | none | yes | searched by term (`q=`) |
| `remotive` | documented API | none | yes | searched by term (`search=`) |
| `linkedin` | **scraped**, through JobSpy | none; proxy optional | yes | descriptions arrive with the posting (`fetch_description=True`), at one extra request each |
| `indeed` | **scraped**, through JobSpy | none; proxy optional | yes | searches nothing until your preferences hold a region it recognises (see below) |
| `arbeitnow` | documented API | none | no | a catalogue with no search, so it fills the database with unrelated jobs; kept registered so the contract test keeps proving it accepts both kinds of source |

`SOURCES` (env) picks which are enabled; the default is `himalayas,remotive,linkedin,indeed`.

### Read this before the first run: LinkedIn and Indeed are scraped

LinkedIn and Indeed have no public jobs API. JobScout collects them by **scraping, through the
[JobSpy](https://github.com/speedyapply/JobSpy) library**, and that is a different thing from the
other sources. It violates those sites' terms of use. It can break whenever a page or endpoint
changes, or stop working the day the site decides to block you. And it runs **from your own IP
address**, because you cloned this and you are the one running it. If you would rather not, take
`linkedin` and `indeed` out of `SOURCES`; everything else keeps working.

`JOBSPY_PROXIES` can route the scraping through a proxy. It is optional, empty by default, and
proxies that LinkedIn will not block are paid; nothing in JobScout requires one. To stay under
the sites' rate limits a proxy-less clone searches little: `JOBSPY_MAX_TERMS` (3) terms per run,
`JOBSPY_RESULTS_WANTED` (10) postings per term, nothing older than `JOBSPY_HOURS_OLD` (168)
hours. Raise them and you raise the chance of being blocked. A blocked site fails only itself:
the run is still ok if any source answered, and the failure is named in the run's `error`.

### Indeed needs a region

Indeed is split by country (`br.indeed.com`, `www.indeed.com`), there is no worldwide Indeed, and
JobSpy would otherwise default to the US. So `indeed` **returns nothing, without searching, until
`regions` in the search's preferences names a country it recognises**, and says so in the run's
`error`. Answer the regions question of the search's conversation (`POST /searches/{id}/answers`),
not the environment.

Recognised: Brazil, Portugal, Spain, USA, UK, Germany, Canada, in English or the local spelling
(`Brasil`, `Alemanha`, `Reino Unido`, ...), plus the two-letter codes except `CA`, which is
ambiguous with California; write `Canada`. Only the first recognised region is searched.

LinkedIn takes the same names: a recognised country is sent to it in English, because LinkedIn
reads `Brazil` but answers `Brasil` with US postings. A region that is not a country (a city,
say) is sent as you typed it.

The same names decide which on-site postings are kept (remote ones always are): `Brasil`,
`Brazil` and `BR` all keep `São Paulo, SP, Brazil`. A location that names no country, like
LinkedIn's `Greater Curitiba`, is kept because the posting records the country it was searched
in, for as long as that country stays in your preferences. A location naming another country
is dropped whatever the search was.

### Checking the scraped sources from your own connection

The scraped sources only run in a **search**: they are asked for the terms extracted from your
profile paragraph. Plain `jobscout fetch` (and the scheduler's ingest) has no terms, so it
returns nothing from `linkedin` and `indeed` and only collects the other sources.

```bash
uv run jobscout serve              # leave it running; set an LLM key in .env first
# in another shell: create a search, answer its questions (regions: Brazil), then
curl -X POST http://127.0.0.1:8000/searches -H "Content-Type: application/json" -d '{"paragraph": "<a paragraph about you>"}'
uv run jobscout search             # or: curl -X POST http://127.0.0.1:8000/searches/1/run
curl "http://127.0.0.1:8000/runs?job=search"
```

The search needs an LLM key, because the terms are extracted from the paragraph by the model.

A healthy run: `sources_ok` equals the number of enabled sources, `sources_failed` is 0,
`fetched` is in the tens (roughly 30 postings per scraped source at the defaults), `errors`
is 0, and the `GET /runs?job=search` row has `"ok": true` and `"error": null`. `GET /searches/{id}/matches`
then lists ranked jobs whose `job.source` includes `linkedin` and `indeed`.

A blocked site looks like this in `GET /runs?job=search`: `ok` stays `true` if any other
source answered, `counters.sources_failed` is at least 1, and `error` names the site and what
it said, for example `linkedin: ...` followed by the message JobSpy reported (often a 429 or an
auth wall). If every source fails, `ok` is `false`. `indeed: not searched, no region is set`
in `error` is not a block: that is the region note above.

**Fallback.** If a proxy-less run is blocked twice in a row from a residential connection,
LinkedIn moves out of the default `SOURCES` and becomes opt-in, and this README will say why.
It will not be answered by adding a paid proxy to the default path.

## License

MIT

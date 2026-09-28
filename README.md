# JobScout

Open-source AI agent that continuously searches public job-board APIs and matches
postings against **your** profile — with an LLM explaining every score.

> Status: early development. Stages 0–1 (collection, CLI, API — no AI yet) are done; stage 2 (LLM matching) is next.
> See `docs/superpowers/specs/2026-09-19-jobscout-design.md` for the full design and roadmap.

## Quick start

```bash
uv sync --all-groups
cp .env.example .env               # optional; defaults work out of the box
uv run jobscout fetch              # pull jobs from enabled sources into ./jobscout.db
uv run jobscout jobs               # jobs that pass your preferences (newest first)
uv run jobscout jobs --all         # every active job, ignoring preferences
uv run jobscout serve              # API + Swagger UI at http://127.0.0.1:8000/docs
```

Set your preferences through the API (`PUT /preferences`), e.g.

```json
{ "titles": ["AI Engineer", "Machine Learning Engineer"], "work_modes": ["remote"], "regions": ["Germany", "Portugal"] }
```

## Matching (AI)

```bash
cp .env.example .env          # set LLM_PROVIDER and your provider key
uv run jobscout match --dry-run   # ranked candidates, no LLM call (still embeds)
uv run jobscout match             # score them (bounded by MAX_LLM_EVALUATIONS_PER_RUN)
uv run jobscout matches --min-score 70
```

Each match carries a 0–100 score, a written justification, matched and missing skills, and
red flags. A cosine prefilter over cached embeddings decides what is worth an LLM call, so a
run costs a bounded number of requests. `--dry-run` makes no LLM call, but it still embeds
up to `MAX_EMBEDDINGS_PER_RUN` jobs (15 by default, sized to the Gemini free tier's
per-minute token budget) that have no cached vector yet, so it does spend
embedding quota. A real run ends with a summary line whose `pending=` counter is how many
candidates are still waiting for a vector — run `jobscout match` again to score the rest.
Without a provider key, everything except matching still works.

## API

| Method | Path            | Description                                   |
|--------|-----------------|-----------------------------------------------|
| GET    | `/health`       | Liveness                                      |
| GET    | `/jobs`         | Active jobs passing your preferences (`?all=true` to ignore them, `?limit=`) |
| GET    | `/preferences`  | Current preferences                           |
| PUT    | `/preferences`  | Partial update; only sent fields change       |
| GET    | `/matches`      | Scored matches, best first (`?min_score=`, `?status=`, `?limit=`) |

## Development

```bash
uv run pytest                      # unit tests, no network
uv run pytest -m integration       # opt-in tests against real APIs
uv run pytest tests/sources/test_arbeitnow.py::test_fetch_maps_fields   # single test
uv run ruff check . && uv run ruff format .
uv run mypy src               # static typing (strict, src only)
```

Adding a job source: implement `JobSource` in `src/jobscout/sources/<name>.py` returning `RawJob`s,
register it in `sources/registry.py`, add `tests/fixtures/<name>_sample.json` and one line in
`tests/sources/test_contract.py`. The contract test does the rest.

## Job sources

- [Arbeitnow](https://www.arbeitnow.com) — free public API, Europe/remote focus.

## License

MIT

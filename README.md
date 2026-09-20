# JobScout

Open-source AI agent that continuously searches public job-board APIs and matches
postings against **your** profile — with an LLM explaining every score.

> Status: early development. Stage 1 (collection, no AI yet) in progress.
> See `docs/superpowers/specs/2026-09-19-jobscout-design.md` for the full design and roadmap.

## Quick start

```bash
uv sync --all-groups
cp .env.example .env          # optional; defaults work out of the box
uv run jobscout fetch         # pull jobs from Arbeitnow into ./jobscout.db
uv run jobscout jobs          # list jobs that pass your preferences
uv run jobscout serve         # API at http://127.0.0.1:8000/docs
```

## Development

```bash
uv run pytest                 # unit tests (no network)
uv run pytest -m integration  # hits real APIs; opt-in
uv run ruff check . && uv run ruff format .
```

## Job sources

- [Arbeitnow](https://www.arbeitnow.com) — free public API, Europe/remote focus.

## License

MIT

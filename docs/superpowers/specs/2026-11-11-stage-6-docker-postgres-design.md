# Stage 6: Docker + Postgres

Date: 2026-11-11. Supersedes the stage 6 row of `2026-09-19-jobscout-design.md` (auth and
multi-user dropped on 2026-11-11; Reflex and i18n on 2026-10-22).

## 1. Intent

JobScout should run 24 hours a day on a VPS, collecting and scoring jobs on its own, and its
page should open from anywhere, including a phone. The first user is the author; later, anyone
who finds the repo should get the same result by following the README. Installing is the
product for a self-hosted project, so the bar is: clone, fill in `.env`, `docker compose up`.

Success: on a fresh Linux VPS with Docker, the README's steps bring up the app and Postgres,
the scheduler runs, the page opens on the author's phone over Tailscale, and a restart of the
VPS brings everything back with the data intact.

## 2. Goals

1. A `Dockerfile` producing an image that runs `jobscout serve` (API, page, scheduler).
2. A `docker-compose.yml` with two services, the app and Postgres, data on a named volume,
   both restarting on failure and on boot.
3. Postgres as a supported database, proven by the test suite running against it in CI.
4. Safe by default: nothing reachable from outside the machine unless the operator adds a
   tunnel or proxy.
5. README section "Run with Docker on a VPS", with Tailscale as the main access path and
   Caddy as the documented alternative.

## 3. Non-goals and anti-goals

- **No auth, no multi-user, no `ACCESS_TOKEN`.** Protection is the localhost bind; exposing
  the app is the operator's job. Everything stays keyed by `user_id` as today.
- No hosted demo, no Kubernetes, no Helm, no Celery/Redis.
- No SQLite → Postgres data migration: the author starts from zero on the VPS.
- No change to the development workflow: contributors keep `uv run` and SQLite.
- Anti-goal: an image or compose that publishes a port on `0.0.0.0`. A forgotten firewall on
  a VPS would expose the page and let anyone spend the operator's LLM key.
- Anti-goal: a database password or LLM key baked into the image or committed.

## 4. Decided by the user

- Stage 6 is Postgres + Docker only (auth dropped).
- The target is a VPS; access from anywhere, including a phone.
- Localhost bind by default (`serve` already defaults `API_HOST=127.0.0.1`; Docker publishes
  the port only on `127.0.0.1`).
- The README documents reverse proxy / tunnel options; no token in the app.
- Start from zero on the VPS; no data migration.

## 5. Design (builder's calls marked *[call]*)

### 5.1 Image

- Multi-stage build on `python:3.12-slim`, dependencies installed with `uv sync --locked
  --no-dev` from `uv.lock` (the uv binary copied from the official `ghcr.io/astral-sh/uv`
  image, pinned). The final stage carries the venv and `src/`, runs as a non-root user.
- Command: `jobscout serve --host 0.0.0.0 --port 8000`. Inside the container `0.0.0.0` is
  required; the outside world is still kept out by the compose port mapping (5.2).
- `HEALTHCHECK` hitting `GET /status`. *[call]*
- `.dockerignore` excludes `.env`, `*.db*`, `.venv`, `tests`, `docs`, caches, `.git`.
- Images for `linux/amd64` and `linux/arm64` (ARM VPSes are common and cheap). *[call]*

### 5.2 Compose

- `db`: `postgres:17-alpine` *[call]*, `POSTGRES_USER/DB=jobscout`, password from
  `POSTGRES_PASSWORD` in `.env` (compose fails with a clear message if unset), named volume
  `pgdata`, a `pg_isready` healthcheck, **no published port**.
- `app`: the image, `env_file: .env`, `DATABASE_URL` set by compose to
  `postgresql+psycopg://jobscout:${POSTGRES_PASSWORD}@db:5432/jobscout` (overriding any
  value in `.env`), `SCHEDULER_ENABLED=true` by default (overridable), `depends_on: db`
  with `condition: service_healthy`, ports `127.0.0.1:8000:8000`, `restart: unless-stopped`.
- `TZ` passed through from `.env` (default `UTC`), because `DIGEST_HOUR` is read in the
  server's local time and a container is UTC otherwise.
- The app service names both `image: ghcr.io/<owner>/jobscout:latest` and `build: .`, so
  `docker compose up` pulls the published image and `docker compose up --build` builds
  locally. *[call]*

### 5.3 Postgres support

- Add `psycopg[binary]` as a runtime dependency. *[call: main dependency rather than an
  extra, so the one image serves both databases]*
- Schema stays on `SQLModel.metadata.create_all` at startup; no Alembic in this stage. A
  fresh Postgres gets the current schema. `upgrade-db` stays SQLite-only (it already refuses
  other dialects). Known limitation, recorded in the README: a future schema change will need
  a migration tool before Postgres users can upgrade in place. *[call]*
- Audit for SQLite-only behaviour the tests never exercised: case sensitivity of `LIKE`/
  comparisons, naive vs aware datetimes, `bytes` embedding columns, JSON columns, ordering
  ties, string length limits, and anything relying on SQLite's type looseness. Fix in the
  code, not in the tests.

### 5.4 Tests and CI

- The `engine` fixture reads an optional `TEST_DATABASE_URL`; unset, it stays in-memory
  SQLite (default, fast, no Docker needed locally). Set to a Postgres URL, each test gets a
  clean schema (drop/create or truncate; builder's choice for speed).
- Tests that are SQLite-specific by nature (`upgrade-db`, `backup_sqlite`) skip on Postgres.
- CI gains a job running `pytest` with a `postgres:17` service container and
  `TEST_DATABASE_URL` set. The existing job is unchanged.
- CI builds the image on every PR (no push) so a broken `Dockerfile` fails the PR, and on
  push to `main` builds multi-arch and pushes to GHCR (`latest` + short SHA) using
  `GITHUB_TOKEN`. *[call]*
- A smoke step in CI: `docker compose up -d`, wait for the app healthcheck, `curl
  127.0.0.1:8000/status`, `docker compose down -v`. *[call]*

### 5.5 Configuration

- `.env.example` gains a Docker block: `POSTGRES_PASSWORD=` (required with Docker) and
  `TZ=`, with a note that compose sets `DATABASE_URL` and `SCHEDULER_ENABLED` itself.
- The comment on `API_HOST` says why it defaults to localhost and that Docker overrides it
  inside the container only.

### 5.6 README: "Run with Docker on a VPS"

1. Prerequisites: a Linux VPS with Docker and the compose plugin.
2. `git clone`, `cp .env.example .env`, fill `LLM_API_KEY`, `GOOGLE_API_KEY`,
   `POSTGRES_PASSWORD`, `TZ`; `docker compose up -d`.
3. **Open it from anywhere (main path): Tailscale.** Install Tailscale on the VPS and the
   phone/computer, then `tailscale serve --bg 8000` on the VPS; the page opens at the VPS's
   tailnet HTTPS name, reachable only from the operator's own devices. No domain, no open
   port.
4. Alternatives, shorter: an SSH tunnel (`ssh -L 8000:127.0.0.1:8000 vps`) for occasional
   use from a computer; Caddy with a domain and `basic_auth` for a public address (example
   `Caddyfile`), with a warning that anyone with the password can spend the LLM key.
5. Operations: update (`git pull && docker compose pull && docker compose up -d`), logs
   (`docker compose logs -f app`), backup (`docker compose exec db pg_dump ...`) and restore.
6. A line in the local-run section that `serve` binds to `127.0.0.1` by default and why.

The Tailscale path is verified end to end by the author on the real VPS before the stage is
called done; the Caddy path is documented, not required to be tested.

## 6. Done when

- `docker compose up -d` on a clean Linux machine yields a working page at
  `127.0.0.1:8000`, scheduler running, data in Postgres, and it survives `docker compose
  restart` and a reboot.
- CI is green with the new Postgres test job, the image build, and the compose smoke test.
- The author opens the page from a phone over Tailscale on the real VPS.
- `api/deps.py` docstrings no longer mention auth arriving in stage 6.

## 7. Left to the builder

Exact base-image tags and digests, Dockerfile layer layout, per-test Postgres isolation
strategy, GHCR workflow details, wording of README sections, and how SQLite-only behaviour
found in 5.3 is fixed.

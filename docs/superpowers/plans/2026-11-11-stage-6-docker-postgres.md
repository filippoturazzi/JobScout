# Stage 6: Docker + Postgres Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JobScout runs 24h on a VPS from `docker compose up -d`, on Postgres, reachable only from localhost unless the operator adds Tailscale or a proxy.

**Architecture:** One image (`python:3.12-slim` + `uv sync --locked --no-dev`) running `jobscout serve`; a compose file with that app and `postgres:17-alpine` on a named volume. Postgres support is proven by running the existing suite against it in CI through an optional `TEST_DATABASE_URL`. CI also builds the image on PRs, smoke-tests the compose stack, and pushes a multi-arch image to GHCR from `main`.

**Tech Stack:** Docker, Docker Compose v2, Postgres 17, `psycopg[binary]` 3, GitHub Actions (`docker/build-push-action`, `docker/setup-qemu-action`, `docker/setup-buildx-action`, `docker/login-action`, `docker/metadata-action`).

**Spec:** `docs/superpowers/specs/2026-11-11-stage-6-docker-postgres-design.md`

## Global Constraints

- No auth, no multi-user, no `ACCESS_TOKEN`; everything stays keyed by `user_id`.
- No port published on `0.0.0.0`: the app is `127.0.0.1:8000:8000`, the db publishes none.
- No secret in the image or in git: `.env` and `*.db*` are in `.dockerignore`; `POSTGRES_PASSWORD` comes only from `.env`.
- Inside the container the app binds `0.0.0.0:8000`; outside Docker `API_HOST` keeps its `127.0.0.1` default.
- Compose sets `DATABASE_URL=postgresql+psycopg://jobscout:${POSTGRES_PASSWORD}@db:5432/jobscout` and `SCHEDULER_ENABLED=${SCHEDULER_ENABLED:-true}`; both override `.env` (compose `environment:` outranks `env_file:`).
- `TZ` from `.env`, default `UTC`.
- Image name `ghcr.io/filippoturazzi/jobscout` (lowercase), tags `latest` and `sha-<short>`, platforms `linux/amd64,linux/arm64`.
- Schema stays on `create_all`; no Alembic. `upgrade-db` stays SQLite-only.
- Development is unchanged: `uv run`, SQLite, `uv run pytest` needs no Docker.
- Before every commit: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src`, `uv run pytest` clean.
- Work on branch `feat/stage-6-docker-postgres`; one PR at the end.

## Review Focus

1. `.env` copied from `.env.example` still says `DATABASE_URL=sqlite:///./jobscout.db` → under compose the app must use Postgres anyway (Task 2 smoke asserts the `user` row is in Postgres).
2. `POSTGRES_PASSWORD` missing from `.env` → `docker compose up` refuses with a message naming the variable, instead of starting a passwordless or broken db (Task 2 step).
3. A reboot or `docker compose down` + `up` (without `-v`) → the data is still there (Task 2 smoke compares the user row's `created_at` across a down/up).
4. Someone checks what is reachable → `docker compose port app 8000` prints `127.0.0.1:8000`, and the db has no published port (Task 2 smoke).
5. `TZ=America/Sao_Paulo` in `.env` → Python inside the container sees `-03` (needs zoneinfo data in the slim image; Task 2 smoke).

---

### Task 1: Postgres support and the suite running on it

**Files:**
- Modify: `pyproject.toml` (add `psycopg[binary]>=3.2` to `dependencies`), `uv.lock`
- Modify: `tests/conftest.py` (the `engine` fixture; a `sqlite_only` marker hook)
- Modify: `pyproject.toml` `[tool.pytest.ini_options].markers` (add `sqlite_only`)
- Modify: the SQLite-by-nature tests (`tests/pipeline/test_upgrade.py`, the `old_db`/`backup_sqlite`/`upgrade-db` tests in `tests/test_cli.py`, the `needs_upgrade` tests in `tests/test_db.py`) — mark `@pytest.mark.sqlite_only` only those that use the `engine` fixture or `old_db`; tests building their own `sqlite:///` tmp files need no marker
- Modify: whatever `src/jobscout/**` code the Postgres run shows to be SQLite-only
- Modify: `.github/workflows/ci.yml` (new job `test-postgres`)

**Interfaces:**
- Produces: env var `TEST_DATABASE_URL` read by `tests/conftest.py::engine`; marker `sqlite_only`. Tasks 2–3 rely on `psycopg` being installed in the locked runtime deps.

- [ ] **Step 1: Branch**

`git switch -c feat/stage-6-docker-postgres`, then commit the already-edited docs (`CLAUDE.md`, `docs/superpowers/specs/2026-09-19-jobscout-design.md`, `docs/superpowers/specs/2026-11-11-stage-6-docker-postgres-design.md`, this plan) as `docs: drop auth from stage 6, design Docker + Postgres`.

- [ ] **Step 2: Add the driver**

`uv add "psycopg[binary]>=3.2"`. Check: `uv run python -c "import psycopg; print(psycopg.__version__)"` prints a 3.x version.

- [ ] **Step 3: Make the `engine` fixture switchable**

In `tests/conftest.py`: when `TEST_DATABASE_URL` is unset, behave exactly as today (`sqlite://`). When set, create the engine from it, `SQLModel.metadata.drop_all(engine)`, then `init_db(engine)`, return it, and `engine.dispose()` after the test (yield fixture). Add a `pytest_collection_modifyitems` hook (or `pytest_runtest_setup`) that skips items marked `sqlite_only` with reason `"SQLite-specific; TEST_DATABASE_URL points elsewhere"` when `TEST_DATABASE_URL` is set and not a `sqlite` URL. Register the marker in `pyproject.toml`.

- [ ] **Step 4: Start a local Postgres and run the suite on it**

```bash
docker run -d --name jobscout-test-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=jobscout_test -p 127.0.0.1:55432:5432 postgres:17-alpine
TEST_DATABASE_URL=postgresql+psycopg://postgres:test@127.0.0.1:55432/jobscout_test uv run pytest -q
```
Expected: failures. These are the failing tests of this task; list them.

- [ ] **Step 5: Fix each failure in `src/`, not in the tests**

For each failing test: decide whether it is (a) SQLite-specific by nature → `sqlite_only` marker, or (b) real SQLite-only behaviour in the code → fix the code. Likely suspects: queries comparing, grouping or `DISTINCT`-ing `JSON` columns (Postgres `json` has no equality; switch the query, not the column type, unless a `JSONB` variant via `JSON().with_variant(JSONB, "postgresql")` is the smaller change), unordered results whose order the test assumes (add an explicit `order_by` in the code if the API promises an order), `ilike`/case differences, integer-vs-bool literals, and sequences after explicit-id inserts in tests. Never weaken an assertion to pass.

- [ ] **Step 6: Verify both databases**

Run: `uv run pytest -q` → all pass (SQLite, as before). Run the Step 4 command → all pass, only `sqlite_only` skipped. Then `docker rm -f jobscout-test-pg`.

- [ ] **Step 7: CI job**

Add job `test-postgres` to `.github/workflows/ci.yml`: same setup steps as `test` up to `uv sync`, a `services.postgres` (`postgres:17-alpine`, `POSTGRES_PASSWORD: test`, `POSTGRES_DB: jobscout_test`, port `5432:5432`, `pg_isready` health options), env `TEST_DATABASE_URL: postgresql+psycopg://postgres:test@localhost:5432/jobscout_test`, and one step `uv run pytest`. Lint, mypy and node stay only in `test`.

- [ ] **Step 8: Lint, type check, commit**

Run ruff check, ruff format --check, mypy. Commit: `feat: support Postgres and run the suite on it in CI`.

---

### Task 2: Image and compose stack

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `scripts/compose_smoke.sh`
- Modify: `.env.example` (Docker block; `API_HOST` comment)

**Interfaces:**
- Consumes: `psycopg` in the lock (Task 1); `GET /status` (exists, `src/jobscout/api/routers/status.py`); CLI `jobscout serve --host --port` (exists).
- Produces: `scripts/compose_smoke.sh` (exit 0 = stack healthy), used by Task 3's CI. Compose service names `app` and `db`, volume `pgdata`.

- [ ] **Step 1: Write the smoke script (the failing test)**

`scripts/compose_smoke.sh`, `set -euo pipefail`, run from the repo root, assumes a `.env` exists. It must:
1. `docker compose up -d --build --wait` (fails if a healthcheck never turns healthy; timeout 180s via `--wait-timeout 180`).
2. `curl -fsS http://127.0.0.1:8000/status` succeeds.
3. `docker compose port app 8000` prints exactly `127.0.0.1:8000`; `docker compose port db 5432` fails or prints nothing.
4. `docker compose exec -T db psql -U jobscout -d jobscout -tAc 'select created_at from "user" where id = 1'` returns a non-empty value → save it.
5. `docker compose exec -T app python -c "import time; print(time.strftime('%z'))"` prints the offset matching the `.env` `TZ` (the script exports `EXPECTED_TZ_OFFSET`, default `+0000`, and compares).
6. `docker compose down` (no `-v`), `docker compose up -d --wait`, re-read the `created_at` from step 4 → identical.
7. On exit (trap), `docker compose down -v` only when `SMOKE_CLEANUP=1`.

Run it now with a scratch `.env` containing only `POSTGRES_PASSWORD=smoke` and `TZ=America/Sao_Paulo`: `EXPECTED_TZ_OFFSET=-0300 SMOKE_CLEANUP=1 bash scripts/compose_smoke.sh`. Expected: FAIL (no compose file). Do not lose the developer's real `.env`: move it aside first and put it back after the task.

- [ ] **Step 2: `.dockerignore`**

Exclude `.git`, `.venv`, `**/__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.env`, `.env.*` (but keep `.env.example`), `*.db`, `*.db.*`, `*.db-*`, `tests`, `docs`, `graphify-out`, `node_modules`.

- [ ] **Step 3: `Dockerfile`**

- Builder stage `python:3.12-slim`; `COPY --from=ghcr.io/astral-sh/uv:<pinned 0.x tag> /uv /bin/uv`; `UV_COMPILE_BYTECODE=1`, `UV_LINK_MODE=copy`, `UV_PYTHON_DOWNLOADS=0`; copy `pyproject.toml uv.lock` and run `uv sync --locked --no-dev --no-install-project` (layer cache), then copy `README.md src/` and `uv sync --locked --no-dev`.
- Final stage `python:3.12-slim`: install `tzdata` only if Step 1's TZ check shows it missing; create user `jobscout` (uid 10001) with a home dir; copy `/app` from builder; `ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1`; `USER jobscout`; `EXPOSE 8000`.
- `HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/status', timeout=4)"`.
- `CMD ["jobscout", "serve", "--host", "0.0.0.0", "--port", "8000"]` (exec form, so SIGTERM reaches uvicorn).

- [ ] **Step 4: `docker-compose.yml`**

```yaml
services:
  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_USER: jobscout
      POSTGRES_DB: jobscout
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U jobscout -d jobscout"]
      interval: 5s
      timeout: 3s
      retries: 20
    restart: unless-stopped
  app:
    image: ghcr.io/filippoturazzi/jobscout:latest
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://jobscout:${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}@db:5432/jobscout
      SCHEDULER_ENABLED: ${SCHEDULER_ENABLED:-true}
      TZ: ${TZ:-UTC}
    ports: ["127.0.0.1:8000:8000"]
    depends_on:
      db: {condition: service_healthy}
    restart: unless-stopped
volumes:
  pgdata:
```
This is the spec's exact shape; the YAML is given because every value is pinned.

- [ ] **Step 5: `.env.example`**

Add a `# --- Docker (stage 6) ---` block at the top, after the header: `POSTGRES_PASSWORD=` (required with Docker, any long random string; `openssl rand -hex 24`), `# TZ=America/Sao_Paulo` (the digest hour is local time; containers default to UTC), and a note that compose sets `DATABASE_URL` and `SCHEDULER_ENABLED` itself, so the values below are for running without Docker. Extend the `API_HOST` comment: localhost by default so nothing is exposed; Docker binds `0.0.0.0` inside the container only and publishes on `127.0.0.1`.

- [ ] **Step 6: Run the smoke test**

`EXPECTED_TZ_OFFSET=-0300 SMOKE_CLEANUP=1 bash scripts/compose_smoke.sh` with the scratch `.env` from Step 1. Expected: exit 0. Then with a `.env` lacking `POSTGRES_PASSWORD`: `docker compose config` fails with `Set POSTGRES_PASSWORD in .env`. Restore the real `.env`.

- [ ] **Step 7: Commit**

`feat: Dockerfile and compose stack with Postgres, localhost-only`.

---

### Task 3: CI for the image

**Files:**
- Create: `.github/workflows/docker.yml`

**Interfaces:**
- Consumes: `scripts/compose_smoke.sh`, `Dockerfile`, `docker-compose.yml` (Task 2).

- [ ] **Step 1: Workflow**

Triggers: `pull_request` and `push` to `main`. `permissions: contents: read, packages: write`.
- Job `smoke` (both triggers): checkout; write a `.env` with `POSTGRES_PASSWORD=ci-smoke` and `TZ=America/Sao_Paulo`; `EXPECTED_TZ_OFFSET=-0300 SMOKE_CLEANUP=1 bash scripts/compose_smoke.sh`.
- Job `publish` (`if: github.event_name == 'push'`, `needs: smoke`): setup-qemu, setup-buildx, login to `ghcr.io` with `${{ github.actor }}` / `${{ secrets.GITHUB_TOKEN }}`, metadata-action for `ghcr.io/filippoturazzi/jobscout` with tags `type=raw,value=latest` and `type=sha`, build-push-action with `platforms: linux/amd64,linux/arm64`, `push: true`, `cache-from/to: type=gha`.

- [ ] **Step 2: Validate**

Run: `docker run --rm -v "$PWD:/repo" rhysd/actionlint:latest -color` (or `actionlint` if installed) → no errors. The real run happens on the PR.

- [ ] **Step 3: Commit**

`ci: smoke-test the compose stack and publish the image to GHCR`.

Manual follow-up for the author after the first push to `main` (record it in the PR description): GitHub → Packages → `jobscout` → Package settings → change visibility to Public, so others can pull without logging in.

---

### Task 4: Docs and leftovers

**Files:**
- Modify: `README.md` (new `## Run with Docker on a VPS` after `## Quick start`; status blurb at the top; `serve` localhost line in Quick start)
- Modify: `src/jobscout/api/deps.py` (lines 1 and 27 docstrings)
- Modify: `CLAUDE.md` (`## Current state` says stage 6 is done; `## Commands` gains `docker compose up -d`, `bash scripts/compose_smoke.sh`, `TEST_DATABASE_URL=... uv run pytest`)

- [ ] **Step 1: README section**, in this order, per spec §5.6:
1. Prerequisites (Linux VPS, Docker + compose plugin).
2. `git clone`, `cp .env.example .env`, fill `LLM_API_KEY`, `GOOGLE_API_KEY`, `POSTGRES_PASSWORD`, `TZ`; `docker compose up -d`; `docker compose logs -f app`.
3. "Open it from anywhere: Tailscale" — install on the VPS and on the phone/computer (`curl -fsSL https://tailscale.com/install.sh | sh`, `sudo tailscale up`), then `sudo tailscale serve --bg 8000`; open `https://<vps-name>.<tailnet>.ts.net`. Say it is reachable only from the operator's own devices and needs no domain or open port.
4. Alternatives: SSH tunnel `ssh -L 8000:127.0.0.1:8000 user@vps`; Caddy with a domain — a `Caddyfile` example with `reverse_proxy 127.0.0.1:8000` and `basic_auth` (hash via `caddy hash-password`), plus the warning that anyone with the password can spend the LLM key.
5. Operations: update (`git pull && docker compose pull && docker compose up -d`), backup (`docker compose exec -T db pg_dump -U jobscout jobscout > jobscout-$(date +%F).sql`), restore (`docker compose exec -T db psql -U jobscout jobscout < file.sql` on an empty volume), and the known limitation: no migration tool yet, so a future schema change will need one before Postgres installs can upgrade in place.
6. In Quick start, one line: `serve` binds to `127.0.0.1` by default so nothing is exposed; set `API_HOST` only if you know you want otherwise.

- [ ] **Step 2: `deps.py` docstrings** — drop "auth will replace in stage 6"; say the app is single-user and this returns the fixed user.

- [ ] **Step 3: Verify and commit**

`uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest -q` → clean. Commit `docs: run JobScout with Docker on a VPS`.

- [ ] **Step 4: PR**

Push, open the PR against `main` with the summary, the GHCR visibility follow-up, and the one manual check left to the author: open the page from a phone over Tailscale on the real VPS (spec §6). Wait for both workflows to go green.

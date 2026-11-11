#!/usr/bin/env bash
# Smoke test for the Docker stack: builds and starts it, then checks what an operator relies
# on. Run from the repo root with a .env holding at least POSTGRES_PASSWORD.
#
#   EXPECTED_TZ_OFFSET  the UTC offset the app should see, as `+0000` / `-0300` (default +0000)
#   SMOKE_CLEANUP=1     remove the containers and the volume on exit
#
# It runs under its own compose project name, so it never touches a real installation's
# containers or data volume.
set -euo pipefail

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-jobscout-smoke}"
expected_offset="${EXPECTED_TZ_OFFSET:-+0000}"

fail() {
    echo "SMOKE FAIL: $*" >&2
    docker compose logs --tail 50 app >&2 || true
    exit 1
}

cleanup() {
    if [[ "${SMOKE_CLEANUP:-0}" == "1" ]]; then
        docker compose down -v --remove-orphans >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

user_created_at() {
    docker compose exec -T db psql -U jobscout -d jobscout -tAc \
        'select created_at from "user" where id = 1'
}

echo "1. build and start"
docker compose up -d --build --wait --wait-timeout 180 || fail "stack did not become healthy"

echo "2. the API answers"
curl -fsS http://127.0.0.1:8000/status >/dev/null || fail "GET /status failed"

echo "3. only localhost is published"
app_port="$(docker compose port app 8000)"
[[ "$app_port" == "127.0.0.1:8000" ]] || fail "app published on '$app_port', want 127.0.0.1:8000"
# `docker port` lists a container's published ports; the db must have none.
db_ports="$(docker port "$(docker compose ps -q db)")"
[[ -z "$db_ports" ]] || fail "db publishes '$db_ports', want nothing"

echo "4. the app writes to Postgres"
created_at="$(user_created_at)"
[[ -n "$created_at" ]] || fail "no default user in Postgres"

echo "5. TZ reaches the app"
offset="$(docker compose exec -T app python -c "import time; print(time.strftime('%z'))" | tr -d '\r')"
[[ "$offset" == "$expected_offset" ]] || fail "app sees UTC offset $offset, want $expected_offset"

echo "6. data survives down + up"
docker compose down
docker compose up -d --wait --wait-timeout 180 || fail "stack did not come back"
[[ "$(user_created_at)" == "$created_at" ]] || fail "default user changed across down/up"

echo "SMOKE OK"

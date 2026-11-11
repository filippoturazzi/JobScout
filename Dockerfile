# JobScout: API, page and scheduler in one process (`jobscout serve`).
# Built for docker-compose.yml, which adds Postgres and publishes the port on localhost only.

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 jobscout
WORKDIR /app
COPY --from=builder --chown=jobscout:jobscout /app /app
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER jobscout
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/status', timeout=4)"]
# 0.0.0.0 inside the container only: compose publishes it on 127.0.0.1 of the host.
CMD ["jobscout", "serve", "--host", "0.0.0.0", "--port", "8000"]

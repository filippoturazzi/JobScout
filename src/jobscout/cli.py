"""Command-line interface. Thin shell over ``jobscout.pipeline``."""

from typing import Annotated

import typer
import uvicorn
from sqlmodel import Session

from jobscout.config import get_settings
from jobscout.db import create_engine_from_url, init_db
from jobscout.pipeline.run import list_jobs, run_ingest
from jobscout.pipeline.users import get_or_create_default_user

app = typer.Typer(help="JobScout: find jobs that match your profile.", no_args_is_help=True)


def _session() -> Session:
    engine = create_engine_from_url(get_settings().database_url)
    init_db(engine)
    return Session(engine)


@app.command()
def fetch() -> None:
    """Fetch jobs from all enabled sources into the database."""
    settings = get_settings()
    with _session() as session:
        user = get_or_create_default_user(session)
        results = run_ingest(session, settings, user.id)
    failed = False
    for r in results:
        if r.error:
            failed = True
            typer.echo(f"{r.source}: ERROR {r.error}")
        else:
            typer.echo(
                f"{r.source}: fetched={r.fetched} created={r.created} "
                f"updated={r.updated} changed={r.changed}"
            )
    if failed:
        raise typer.Exit(code=1)


@app.command()
def jobs(
    limit: Annotated[int, typer.Option(help="Max rows to show.")] = 20,
    all_jobs: Annotated[
        bool, typer.Option("--all", help="Ignore preferences; show every active job.")
    ] = False,
) -> None:
    """List active jobs that pass your preferences (newest first)."""
    with _session() as session:
        user = get_or_create_default_user(session)
        rows = list_jobs(session, user.id, limit=limit, apply_filters=not all_jobs)
        if not rows:
            typer.echo("No jobs found. Run `jobscout fetch` first or relax your preferences.")
            return
        for job in rows:
            mode = "remote" if job.remote else (job.location or "n/a")
            typer.echo(f"[{job.source}] {job.title} — {job.company} ({mode})\n    {job.url}")


@app.command()
def serve(
    host: Annotated[str | None, typer.Option()] = None,
    port: Annotated[int | None, typer.Option()] = None,
    reload: Annotated[bool, typer.Option(help="Auto-reload on code changes.")] = False,
) -> None:
    """Run the HTTP API (docs at /docs)."""
    settings = get_settings()
    uvicorn.run(
        "jobscout.api.app:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
    )

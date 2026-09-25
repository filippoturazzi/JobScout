"""Command-line interface. Thin shell over ``jobscout.pipeline``."""

import logging
from typing import Annotated

import typer
import uvicorn
from sqlmodel import Session

from jobscout.config import get_settings
from jobscout.db import get_engine, init_db
from jobscout.matching.llm import MissingProviderError
from jobscout.pipeline.matching import run_match
from jobscout.pipeline.run import list_jobs, list_matches, run_ingest
from jobscout.pipeline.users import get_or_create_default_user

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

app = typer.Typer(help="JobScout: find jobs that match your profile.", no_args_is_help=True)


def _session() -> Session:
    engine = get_engine(get_settings())
    init_db(engine)
    return Session(engine)


@app.command()
def fetch() -> None:
    """Fetch jobs from all enabled sources into the database."""
    settings = get_settings()
    with _session() as session:
        try:
            results = run_ingest(session, settings)
        except ValueError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=2) from exc
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
        assert user.id is not None, "a persisted user always has an id"
        rows = list_jobs(session, user.id, limit=limit, apply_filters=not all_jobs)
        if not rows:
            typer.echo("No jobs found. Run `jobscout fetch` first or relax your preferences.")
            return
        for job in rows:
            mode = "remote" if job.remote else (job.location or "n/a")
            typer.echo(f"[{job.source}] {job.title} — {job.company} ({mode})\n    {job.url}")


@app.command()
def match(
    limit: Annotated[int | None, typer.Option(help="Evaluate at most this many jobs.")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be evaluated; call no LLM.")
    ] = False,
) -> None:
    """Score the best unmatched jobs against your profile."""
    settings = get_settings()
    with _session() as session:
        user = get_or_create_default_user(session)
        assert user.id is not None, "a persisted user always has an id"
        try:
            result = run_match(session, settings, user.id, limit=limit, dry_run=dry_run)
        except MissingProviderError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=2) from exc

    if result.error:
        typer.echo(result.error)
        return
    if dry_run:
        if not result.previewed:
            typer.echo(f"Nothing to evaluate ({result.candidates} candidates).")
            return
        typer.echo(f"Would evaluate {len(result.previewed)} of {result.candidates} candidates:")
        for _job_id, similarity, title in result.previewed:
            typer.echo(f"  {similarity:.3f}  {title}")
        return
    typer.echo(
        f"candidates={result.candidates} evaluated={result.evaluated} "
        f"skipped_low={result.skipped_low} errors={len(result.errors)}"
    )
    for message in result.errors:
        typer.echo(f"  ERROR {message}", err=True)
    if result.errors and result.evaluated == 0 and result.skipped_low == 0:
        raise typer.Exit(code=1)


@app.command()
def matches(
    min_score: Annotated[int, typer.Option(help="Only show matches at or above this score.")] = 0,
    limit: Annotated[int, typer.Option(help="Max rows to show.")] = 20,
) -> None:
    """List scored matches, best first."""
    with _session() as session:
        user = get_or_create_default_user(session)
        assert user.id is not None, "a persisted user always has an id"
        rows = list_matches(session, user.id, min_score=min_score, limit=limit)
        if not rows:
            typer.echo("No matches yet. Run `jobscout match` after setting your profile summary.")
            return
        for match_row, job in rows:
            typer.echo(f"[{match_row.score}] {job.title} — {job.company}")
            if match_row.reasoning:
                typer.echo(f"    {match_row.reasoning}")
            typer.echo(f"    {job.url}")


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind address.")] = None,
    port: Annotated[int | None, typer.Option(help="Bind port.")] = None,
    reload: Annotated[bool, typer.Option(help="Auto-reload on code changes.")] = False,
) -> None:
    """Run the HTTP API (docs at /docs)."""
    settings = get_settings()
    uvicorn.run(
        "jobscout.api.app:app",
        host=host if host is not None else settings.api_host,
        port=port if port is not None else settings.api_port,
        reload=reload,
    )

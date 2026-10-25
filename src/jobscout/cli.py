"""Command-line interface. Thin shell over ``jobscout.pipeline``."""

import logging
from typing import Annotated

import typer
import uvicorn
from sqlmodel import Session

from jobscout.config import Settings, get_settings
from jobscout.db import get_engine, init_db
from jobscout.logs import configure_logging
from jobscout.pipeline.matching import MissingProviderError, run_match
from jobscout.pipeline.repair import repair_descriptions as repair
from jobscout.pipeline.run import list_jobs, list_matches, run_ingest
from jobscout.pipeline.search import SearchProgress, run_search
from jobscout.pipeline.users import get_or_create_default_user
from jobscout.sources.registry import source_statuses

configure_logging()
log = logging.getLogger(__name__)

app = typer.Typer(
    help="JobScout: find jobs that match your profile.",
    no_args_is_help=True,
    # Unattended runs land in log files and Windows consoles, where a colourised
    # traceback is unreadable.
    pretty_exceptions_enable=False,
)


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
                f"updated={r.updated} changed={r.changed} merged={r.merged}"
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
        except Exception as exc:  # a 429 or a dropped connection is not a traceback's worth
            # Debug, not error: the stack is noise in a terminal, and the one-line message
            # below is the CLI's contract. Raise the log level to get it back.
            log.debug("match failed", exc_info=True)
            typer.echo(f"Error: {type(exc).__name__}: {exc}", err=True)
            # Exit 2 is "the provider could not be used"; exit 1 below is "it ran and
            # every candidate failed". A wrapping script needs to tell those apart.
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
        f"skipped_low={result.skipped_low} embedded={result.embedded} "
        f"pending={result.embeddings_pending} errors={len(result.errors)}"
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
            if min_score > 0:
                # Having matched and found nothing good is not the same as never matching.
                typer.echo(f"No matches scoring {min_score} or above. Try a lower --min-score.")
                return
            typer.echo("No matches yet. Run `jobscout match` after setting your profile summary.")
            return
        for match_row, job in rows:
            typer.echo(f"[{match_row.score}] {job.title} — {job.company}")
            if match_row.reasoning:
                typer.echo(f"    {match_row.reasoning}")
            typer.echo(f"    {job.url}")


def _progress_line(progress: SearchProgress, settings: Settings) -> str:
    if progress.stage == "terms":
        return f"terms: {', '.join(progress.terms)}"
    if progress.stage == "source":
        if progress.error is not None:
            return f"{progress.source}: failed for {progress.term!r}: {progress.error}"
        if progress.term is None:  # a catalogue source, asked once with no term
            return f"{progress.source}: {progress.fetched} postings"
        return f"{progress.source}: {progress.fetched} postings for {progress.term!r}"
    if progress.stage == "scoring":
        return (
            f"scoring {progress.total} candidates (embeddings first, then up to "
            f"{settings.max_llm_evaluations_per_run} LLM evaluations)"
        )
    return f"  evaluated {progress.done}/{progress.total}"


@app.command()
def search(
    limit: Annotated[int, typer.Option(help="Max matches to show afterwards.")] = 20,
) -> None:
    """Search every source with the terms from your profile, score, and show the ranking.

    The same run `POST /search` starts, here in the foreground, printing each step as it
    happens. It needs an LLM key: the terms are extracted from your profile paragraph.
    """
    settings = get_settings()
    try:
        statuses = source_statuses(settings)
    except ValueError as exc:  # a typo in SOURCES
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    for status in statuses:
        if not status.active:
            typer.echo(f"{status.name}: dormant ({status.reason})")
    with _session() as session:
        user = get_or_create_default_user(session)
        assert user.id is not None, "a persisted user always has an id"
        # Printed as it happens: a search takes minutes (a scraped source makes one request
        # per posting), and a command silent for that long reads as hung.
        result = run_search(
            session,
            settings,
            user.id,
            on_progress=lambda progress: typer.echo(_progress_line(progress, settings)),
        )
        typer.echo(" ".join(f"{name}={value}" for name, value in result.counters.items()))
        for message in result.errors:
            typer.echo(f"  ERROR {message}")
        if result.remaining:
            typer.echo(f"{result.remaining} candidates left for the next run (the per-run caps).")
        rows = list_matches(session, user.id, limit=limit)
        for match_row, job in rows:
            typer.echo(f"[{match_row.score}] {job.title} — {job.company}")
            typer.echo(f"    {job.url}")
    if not result.ok:
        raise typer.Exit(code=1)


@app.command()
def repair_descriptions() -> None:
    """Re-render stored job text after a renderer fix, using each row's saved payload.

    Offline: no source is contacted. Repaired rows lose the embedding computed from the
    old text and have their matches marked stale, so the next `match` run rescores them.
    """
    with _session() as session:
        stats = repair(session)
    typer.echo(f"repaired={stats.repaired} unchanged={stats.unchanged} no_payload={stats.skipped}")
    if stats.repaired:
        typer.echo("Run `jobscout match` to re-embed and rescore the repaired jobs.")


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

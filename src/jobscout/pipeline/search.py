"""One user-initiated search: terms -> every registered source -> scoring, in one run.

This is the composer the whole stage exists for, and it composes rather than implements:
``pipeline.ingest.ingest`` owns persistence, ``pipeline.matching.run_match`` owns embedding,
ranking and the per-run caps, ``matching.terms`` owns the paragraph. What is new here is
choosing the terms, walking the sources with one failure isolated from the next, and keeping
the counters current while the run is still going — the page polls them.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from sqlmodel import Session

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps
from jobscout.models import Run, Search, UserPreferences
from jobscout.models.base import utcnow
from jobscout.pipeline.ingest import ingest
from jobscout.pipeline.matching import run_match, select_candidates
from jobscout.pipeline.searches import record_fetched
from jobscout.pipeline.users import get_preferences
from jobscout.sources.base import JobSource, SearchQuery
from jobscout.sources.regions import country_of
from jobscout.sources.registry import build_sources, source_statuses

log = logging.getLogger(__name__)

__all__ = [
    "MAX_TERMS_PER_SOURCE",
    "NoUsableSourcesError",
    "SearchProgress",
    "SearchResult",
    "open_search_run",
    "run_search",
]

MAX_TERMS_PER_SOURCE = 5
"""How many of the ranked terms each searchable source is asked for, one page each.

Spec 5.1 says 3-5. The terms are ordered most important first, so taking the head is the
ranking; more terms means more requests against free APIs for steadily worse keywords.
"""


class NoUsableSourcesError(RuntimeError):
    """Nowhere to fetch from: every configured source is dormant, or none is configured."""


@dataclass
class SearchResult:
    """What one search did. ``counters`` is the subset the Run row and the page carry."""

    run_id: int | None = None
    ok: bool = False
    terms: list[str] = field(default_factory=list)
    fetched: int = 0
    sources_ok: int = 0
    sources_failed: int = 0
    candidates: int = 0
    evaluated: int = 0
    embedded: int = 0
    remaining: int = 0
    to_score: int = 0
    scored: int = 0
    errors: list[str] = field(default_factory=list)
    # Per-source progress as `Run.sources` stores it; the page draws one line from each.
    sources: list[dict[str, object]] = field(default_factory=list)

    @property
    def counters(self) -> dict[str, int]:
        return {
            "fetched": self.fetched,
            "sources_ok": self.sources_ok,
            "sources_failed": self.sources_failed,
            "candidates": self.candidates,
            "evaluated": self.evaluated,
            "embedded": self.embedded,
            "remaining": self.remaining,
            "to_score": self.to_score,
            "scored": self.scored,
            "errors": len(self.errors),
        }


@dataclass(frozen=True)
class SearchProgress:
    """One step of a search, for a caller that shows it while the run is still going.

    ``terms``: the terms were resolved. ``source``: one source answered one term (or failed
    on it, with ``error``); ``fetched`` is what that one call returned. ``scoring``: the
    fetch is over and ``total`` candidates are pending. ``evaluated``: ``done`` of the
    ``total`` jobs selected for scoring are finished.
    """

    stage: Literal["terms", "source", "scoring", "evaluated"]
    terms: list[str] = field(default_factory=list)
    source: str | None = None
    term: str | None = None
    fetched: int = 0
    error: str | None = None
    done: int = 0
    total: int = 0


def open_search_run(session: Session, search_id: int) -> Run:
    """Open the row before any work starts, so a killed process leaves a failure behind.

    Public so a caller that runs the search in the background can hand out the run's id
    before the work begins, then pass it to ``run_search``.

    Not ``scheduler.start_run``: ``pipeline`` sits below ``scheduler`` and must not import
    it, and a search has no business pruning the operator's run history on the way past.
    """
    search = session.get(Search, search_id)
    if search is None:
        raise LookupError(f"No search {search_id}")
    run = Run(job="search", user_id=search.user_id, search_id=search_id)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _publish(session: Session, run: Run, result: SearchResult) -> None:
    """Write the counters mid-flight. The page polls them while the run is still going."""
    run.counters = result.counters
    run.sources = [dict(entry) for entry in result.sources]
    session.add(run)
    session.commit()


def _finish(session: Session, run: Run, result: SearchResult, ok: bool) -> None:
    result.ok = ok
    run.ok = ok
    run.counters = result.counters
    run.sources = [dict(entry) for entry in result.sources]
    run.error = "; ".join(result.errors) or None
    run.finished_at = utcnow()
    session.add(run)
    session.commit()


def _usable_sources(settings: Settings) -> list[JobSource]:
    """The sources that will actually run, or an error naming why none will.

    ``build_sources`` drops a source whose credentials are absent and returns an empty list
    without complaining. A search that fetched nothing because there was nowhere to fetch
    from is not a clean run, so say what is dormant and what would wake it.
    """
    sources = build_sources(settings)
    if sources:
        return sources
    dormant = [status for status in source_statuses(settings) if not status.active]
    if dormant:
        detail = ", ".join(f"{status.name} ({status.reason})" for status in dormant)
        raise NoUsableSourcesError(
            f"no usable sources: every configured source is dormant: {detail}"
        )
    raise NoUsableSourcesError("no sources are configured (SOURCES is empty)")


def _search_places(regions: list[str]) -> list[str]:
    """The places worth a search of their own: one entry per country, in the user's order.

    A city beside a country adds nothing: the country's search already covers it, and only a
    country is trusted to narrow a search. Regions that name no country are searched as typed
    only when no country was given.
    """
    typed = [region.strip() for region in regions if region.strip()]
    by_country: dict[str, str] = {}
    for region in typed:
        country = country_of(region)
        if country is not None:
            by_country.setdefault(country, region)
    return list(by_country.values()) or list(dict.fromkeys(typed))


def _queries_for(source: JobSource, terms: list[str], prefs: UserPreferences) -> list[SearchQuery]:
    if not source.supports_search:
        # A catalogue source ignores the query and returns everything it has; asking it
        # once per term would download the same catalogue five times over.
        return [SearchQuery()]
    budget = source.term_budget or MAX_TERMS_PER_SOURCE
    # The same reading `pipeline.filters` gives work modes: "remote" is the one that means
    # remote work. Both lists are free text the user set by hand and are often empty,
    # which is the normal case: an empty query field simply does not narrow the search.
    modes = {mode.lower() for mode in prefs.work_modes}
    remote_only = modes == {"remote"}
    places = _search_places(prefs.regions)
    if source.searches_by_location and places:
        # The budget counts requests, because each one risks a block on a scraped site. The
        # best term goes to every country before the next term goes to any.
        pairs = [(term, place) for term in terms for place in places]
        return [
            SearchQuery(
                keywords=[term], locations=[place], remote_only=remote_only, city=prefs.city
            )
            for term, place in pairs[:budget]
        ]
    return [
        SearchQuery(
            keywords=[term],
            locations=list(prefs.regions),
            remote_only=remote_only,
            city=prefs.city,
        )
        for term in terms[:budget]
    ]


def _fetch(
    session: Session,
    search_id: int,
    sources: list[JobSource],
    terms: list[str],
    prefs: UserPreferences,
    result: SearchResult,
    publish: Callable[[], None],
    report: Callable[[SearchProgress], None],
) -> None:
    """Search every source, one term per call, isolating each failure from the rest."""
    seen: set[int] = set()
    modes = {mode.lower() for mode in prefs.work_modes}

    def update_entry(index: int, **changes: object) -> None:
        # A new list each time: the JSON column does not notice a mutated one.
        result.sources = [
            {**entry, **changes} if i == index else entry for i, entry in enumerate(result.sources)
        ]

    for index, source in enumerate(sources):
        if source.all_remote and modes and "remote" not in modes:
            reason = "not searched, it only lists remote jobs"
            result.errors.append(f"{source.name}: {reason}")
            update_entry(index, state="skipped", detail=reason)
            publish()
            continue
        batch: list[JobSource] = [source]
        answered = False
        queries = _queries_for(source, terms, prefs)
        source_seen: set[int] = set()
        failure: str | None = None
        if not queries:
            reason = "not searched, there was nothing to ask it"
            result.errors.append(f"{source.name}: {reason}")
            update_entry(index, state="skipped", detail=reason)
            publish()
            continue
        notes: list[str] = []
        if source.searches_by_location:
            asked = {place for query in queries for place in query.locations}
            notes = [
                f"not searched in {place}, only {len(queries)} searches per run"
                for place in _search_places(prefs.regions)
                if place not in asked
            ]
            result.errors.extend(f"{source.name}: {note}" for note in notes)
        update_entry(index, state="searching", queries_total=len(queries), notes=notes)
        publish()
        try:
            # A failure breaks the loop, so the answered queries are the first `number + 1`.
            for number, query in enumerate(queries):
                (outcome,) = ingest(session, batch, query)
                report(
                    SearchProgress(
                        stage="source",
                        source=source.name,
                        term=query.keywords[0] if query.keywords else None,
                        fetched=outcome.fetched,
                        error=outcome.error,
                    )
                )
                if outcome.error is not None:
                    result.errors.append(f"{source.name}: {outcome.error}")
                    failure = outcome.error
                    # One term per ingest call, so whatever this source already returned is
                    # committed. Its remaining terms are abandoned rather than retried: a
                    # source that just answered 429 will not answer the next four either.
                    break
                answered = True
                record_fetched(session, search_id, outcome.seen_ids)
                seen.update(outcome.seen_ids)
                source_seen.update(outcome.seen_ids)
                result.fetched = len(seen)
                update_entry(index, fetched=len(source_seen), queries_done=number + 1)
                publish()
        except Exception as exc:
            # Never leave the source "searching": the page names failures from this entry.
            session.rollback()
            detail = f"{type(exc).__name__}: {exc}"
            result.errors.append(f"{source.name}: {detail}")
            result.sources_failed += 1
            update_entry(index, state="failed", detail=detail)
            publish()
            raise
        # A source counts as ok once it has answered at all, even if a later term failed:
        # the postings it did return are ingested and real. A source that failed on its
        # first term contributed nothing. Every failure is named in `errors` either way;
        # these two counters only decide whether the run as a whole got anywhere.
        if answered:
            result.sources_ok += 1
        else:
            result.sources_failed += 1
        update_entry(
            index,
            state="done" if answered else "failed",
            # A source that answered and then failed keeps "done"; the page still names why.
            detail=failure,
        )
        publish()
        # A source may note something that is not a failure (a region it could not map,
        # say) in a `warnings` list. Only some sources have one, so it is read with
        # `getattr` rather than widening the protocol. It lands in the source's `notes`,
        # which the page shows under the results, and in `errors` for the run row; it does
        # not touch the ok/failed counters.
        warned = [w for w in dict.fromkeys(getattr(source, "warnings", ())) if w not in notes]
        for warning in warned:
            message = f"{source.name}: {warning}"
            if message not in result.errors:
                result.errors.append(message)
        if warned:
            update_entry(index, notes=[*notes, *warned])
            publish()
    result.fetched = len(seen)


def run_search(
    session: Session,
    settings: Settings,
    search_id: int,
    deps: GraphDeps | None = None,
    run_id: int | None = None,
    on_progress: Callable[[SearchProgress], None] | None = None,
    fetch: bool = True,
) -> SearchResult:
    """Fetch for one search from every registered source, then score what is pending.

    Runs on the confirmed preferences only: the terms are ``prefs.search_terms`` and nothing
    is read from the paragraph here. ``fetch=False`` skips the sources and scores what is
    pending ("Rank the rest"); it is ok when it did not error with nothing evaluated.

    ``run_id`` names a row ``open_search_run`` already wrote; without one, a row is opened
    here. Never raises: it is run in the background and the only way an operator or the
    page learns what happened is the Run row, so every failure is recorded there instead.
    """
    result = SearchResult()
    existing = session.get(Run, run_id) if run_id is not None else None
    run = existing if existing is not None else open_search_run(session, search_id)
    result.run_id = run.id

    def publish() -> None:
        _publish(session, run, result)

    def report(progress: SearchProgress) -> None:
        if on_progress is not None:
            on_progress(progress)

    try:
        prefs = get_preferences(session, search_id)
        result.terms = list(prefs.search_terms)
        if not result.terms:
            raise ValueError(
                "the search has no confirmed terms: answer its questions and press Search jobs"
            )
        sources = _usable_sources(settings) if fetch else []
    except Exception as exc:
        # Nothing was fetched: the run was over before it started and must say why.
        session.rollback()
        log.warning("search %s could not start: %s", search_id, exc)
        result.errors.append(f"{type(exc).__name__}: {exc}")
        _finish(session, run, result, ok=False)
        return result

    result.sources = [
        {
            "name": source.name,
            "state": "waiting",
            "fetched": 0,
            "queries_done": 0,
            "queries_total": 0,
            "detail": None,
            "notes": [],
        }
        for source in sources
    ]
    publish()
    report(SearchProgress(stage="terms", terms=list(result.terms)))
    if fetch:
        try:
            _fetch(session, search_id, sources, result.terms, prefs, result, publish, report)
        except Exception:
            # Not a source refusing (that is an outcome, handled inside): something broke
            # around it. `_fetch` already marked the source failed and named the error.
            log.exception("the search %s stopped while fetching", search_id)
            _finish(session, run, result, ok=False)
            return result

    try:
        # Published before scoring starts so the page has a denominator to show while it
        # runs; `run_match` selects the same set again for itself.
        pending = select_candidates(session, prefs, search_id)
        result.candidates = len(pending)
        result.remaining = len(pending)
        # An estimate for the page while jobs are embedded; replaced by the real selection
        # on the first evaluated job and again once `run_match` returns.
        result.to_score = min(len(pending), settings.max_llm_evaluations_per_run)
        publish()
        report(SearchProgress(stage="scoring", total=len(pending)))

        def evaluated(done: int, total: int) -> None:
            result.scored = done
            result.to_score = total
            publish()
            report(SearchProgress(stage="evaluated", done=done, total=total))

        scored = run_match(
            session,
            settings,
            search_id,
            deps=deps,
            on_evaluated=evaluated,
        )
        if scored.error is not None:
            raise ValueError(scored.error)
        result.candidates = scored.candidates
        result.to_score = scored.selected
        result.scored = min(result.scored, result.to_score)
        result.evaluated = scored.evaluated
        result.embedded = scored.embedded
        # What the caps left for the next run. The `skipped_low` jobs are done, not left:
        # each carries a committed `low` match, which is terminal. Never negative — both
        # counters come from a subset of the same candidate list.
        result.remaining = scored.candidates - scored.evaluated - scored.skipped_low
        result.errors.extend(scored.errors)
    except Exception as exc:
        session.rollback()
        log.exception("scoring failed during the search %s", search_id)
        # The selection is unknown here; never claim more to score than was scored.
        result.to_score = result.scored
        result.errors.append(f"{type(exc).__name__}: {exc}")
        _finish(session, run, result, ok=False)
        return result

    # The same rule `ingest_job` and `match_job` settled on: partial failure is not run
    # failure. The run is ok when at least one source answered and fails when none did,
    # and scoring fails it only when it errored and evaluated nothing at all.
    scored_nothing = len(scored.errors) > 0 and scored.evaluated == 0
    answered = result.sources_ok > 0 if fetch else True
    _finish(session, run, result, ok=answered and not scored_nothing)
    return result

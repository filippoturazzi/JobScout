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

from sqlmodel import Session

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps
from jobscout.matching.llm import chat_model
from jobscout.matching.terms import extract_profile, profile_hash
from jobscout.models import Run
from jobscout.models.base import utcnow
from jobscout.pipeline.ingest import ingest
from jobscout.pipeline.matching import run_match, select_candidates
from jobscout.pipeline.users import get_preferences, update_preferences
from jobscout.sources.base import JobSource, RawJob, SearchQuery
from jobscout.sources.registry import build_sources, source_statuses

log = logging.getLogger(__name__)

__all__ = ["MAX_TERMS_PER_SOURCE", "NoUsableSourcesError", "SearchResult", "run_search"]

MAX_TERMS_PER_SOURCE = 5
"""How many of the ranked terms each searchable source is asked for, one page each.

Spec 5.1 says 3-5. The terms are ordered most important first, so taking the head is the
ranking; more terms means more requests against free APIs for steadily worse keywords.
"""

# Extraction fills these from the paragraph. They are written only when the extraction
# found something: an empty answer must never erase what the user set by hand. `titles`,
# `regions` and `work_modes` are deliberately absent — see `matching.terms`, automatic
# extraction may add exclusions, never restrictions.
_EXTRACTED_PREFERENCES = ("seniority", "required_skills", "excluded_keywords")


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
    errors: list[str] = field(default_factory=list)

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
            "errors": len(self.errors),
        }


class _CountedSource:
    """A source that records the distinct postings it hands back over a whole run.

    One posting answers several terms, and ``fetched`` must count it once or the progress
    bar reports work that does not exist. ``ingest`` returns counts, not keys, so the keys
    are collected here, where the raw postings still exist.
    """

    def __init__(self, source: JobSource, seen: set[tuple[str, str]]) -> None:
        self._source = source
        self._seen = seen
        self.name = source.name
        self.supports_search = source.supports_search

    def fetch(self, query: SearchQuery) -> list[RawJob]:
        jobs = self._source.fetch(query)
        self._seen.update((job.source, job.external_id) for job in jobs)
        return jobs


def _open_run(session: Session, user_id: int) -> Run:
    """Open the row before any work starts, so a killed process leaves a failure behind.

    Not ``scheduler.start_run``: ``pipeline`` sits below ``scheduler`` and must not import
    it, and a search has no business pruning the operator's run history on the way past.
    """
    run = Run(job="search", user_id=user_id)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def _publish(session: Session, run: Run, result: SearchResult) -> None:
    """Write the counters mid-flight. The page polls them while the run is still going."""
    run.counters = result.counters
    session.add(run)
    session.commit()


def _finish(session: Session, run: Run, result: SearchResult, ok: bool) -> None:
    result.ok = ok
    run.ok = ok
    run.counters = result.counters
    run.error = "; ".join(result.errors) or None
    run.finished_at = utcnow()
    session.add(run)
    session.commit()


def _resolve_terms(
    session: Session, settings: Settings, user_id: int, deps: GraphDeps | None
) -> list[str]:
    """The stored terms when the paragraph has not changed, a fresh extraction otherwise.

    Raises ``ValueError`` when the paragraph is empty or yields no usable term, so a search
    for the empty string never reaches the sources.
    """
    prefs = get_preferences(session, user_id)
    paragraph = prefs.profile_summary
    digest = profile_hash(paragraph)
    # The stored terms are only worth reusing when there are some: a matching hash with an
    # empty list would otherwise search for nothing and report a clean, empty run.
    if prefs.profile_hash == digest and prefs.search_terms:
        return list(prefs.search_terms)

    chat = deps.chat if deps is not None else chat_model(settings)
    extracted = extract_profile(paragraph, chat)
    changes: dict[str, object] = {"search_terms": extracted.terms, "profile_hash": digest}
    for name in _EXTRACTED_PREFERENCES:
        found = getattr(extracted, name)
        if found:
            changes[name] = found
    update_preferences(session, user_id, changes)
    return list(extracted.terms)


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


def _queries_for(source: JobSource, terms: list[str]) -> list[SearchQuery]:
    if not source.supports_search:
        # A catalogue source ignores the query and returns everything it has; asking it
        # once per term would download the same catalogue five times over.
        return [SearchQuery()]
    return [SearchQuery(keywords=[term]) for term in terms[:MAX_TERMS_PER_SOURCE]]


def _fetch(
    session: Session,
    sources: list[JobSource],
    terms: list[str],
    result: SearchResult,
    publish: Callable[[], None],
) -> None:
    """Search every source, one term per call, isolating each failure from the rest."""
    seen: set[tuple[str, str]] = set()
    for source in sources:
        counted = _CountedSource(source, seen)
        batch: list[JobSource] = [counted]
        answered = False
        for query in _queries_for(source, terms):
            (outcome,) = ingest(session, batch, query)
            if outcome.error is not None:
                result.errors.append(f"{source.name}: {outcome.error}")
                # One term per ingest call, so whatever this source already returned is
                # committed. Its remaining terms are abandoned rather than retried: a
                # source that just answered 429 will not answer the next four either.
                break
            answered = True
            result.fetched = len(seen)
            publish()
        # A source counts as ok once it has answered at all, even if a later term failed:
        # the postings it did return are ingested and real. A source that failed on its
        # first term contributed nothing. Every failure is named in `errors` either way;
        # these two counters only decide whether the run as a whole got anywhere.
        if answered:
            result.sources_ok += 1
        else:
            result.sources_failed += 1
    result.fetched = len(seen)


def run_search(
    session: Session,
    settings: Settings,
    user_id: int,
    deps: GraphDeps | None = None,
) -> SearchResult:
    """Fetch for one user from every registered source, then score what is pending.

    Never raises: it is run in the background and the only way an operator or the page
    learns what happened is the Run row, so every failure is recorded there instead.
    """
    result = SearchResult()
    run = _open_run(session, user_id)
    result.run_id = run.id

    def publish() -> None:
        _publish(session, run, result)

    try:
        result.terms = _resolve_terms(session, settings, user_id, deps)
        sources = _usable_sources(settings)
    except Exception as exc:
        # Nothing was fetched: the run was over before it started and must say why.
        session.rollback()
        log.warning("search for user %s could not start: %s", user_id, exc)
        result.errors.append(f"{type(exc).__name__}: {exc}")
        _finish(session, run, result, ok=False)
        return result

    publish()
    _fetch(session, sources, result.terms, result, publish)

    try:
        # Published before scoring starts so the page has a denominator to show while it
        # runs; `run_match` selects the same set again for itself.
        prefs = get_preferences(session, user_id)
        pending = select_candidates(session, prefs, user_id)
        result.candidates = len(pending)
        result.remaining = len(pending)
        publish()

        scored = run_match(session, settings, user_id, deps=deps)
        # `run_match`'s only `error` is the empty-profile case, and `_resolve_terms` has
        # already refused that: the paragraph it extracts from IS the profile summary.
        assert scored.error is None, scored.error
        result.candidates = scored.candidates
        result.evaluated = scored.evaluated
        result.embedded = scored.embedded
        # What the caps left for the next run. The `skipped_low` jobs are done, not left:
        # each carries a committed `low` match, which is terminal. Never negative — both
        # counters come from a subset of the same candidate list.
        result.remaining = scored.candidates - scored.evaluated - scored.skipped_low
        result.errors.extend(scored.errors)
    except Exception as exc:
        session.rollback()
        log.exception("scoring failed during the search for user %s", user_id)
        result.errors.append(f"{type(exc).__name__}: {exc}")
        _finish(session, run, result, ok=False)
        return result

    # The same rule `ingest_job` and `match_job` settled on: partial failure is not run
    # failure. The run is ok when at least one source answered and fails when none did,
    # and scoring fails it only when it errored and evaluated nothing at all.
    scored_nothing = len(scored.errors) > 0 and scored.evaluated == 0
    _finish(session, run, result, ok=result.sources_ok > 0 and not scored_nothing)
    return result

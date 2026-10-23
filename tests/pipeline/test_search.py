"""The search run: terms -> every registered source -> scoring, recorded in one Run row."""

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from sqlmodel import Session, select

from jobscout.config import Settings
from jobscout.db import create_engine_from_url, init_db
from jobscout.matching.graph import GraphDeps
from jobscout.matching.schemas import EvaluationResult
from jobscout.matching.terms import ExtractedProfile, profile_hash
from jobscout.models import Job, Match, Run
from jobscout.pipeline.search import MAX_TERMS_PER_SOURCE, run_search
from jobscout.pipeline.users import get_or_create_default_user, get_preferences, update_preferences
from jobscout.sources.arbeitnow import BASE_URL as ARBEITNOW_URL
from jobscout.sources.himalayas import BASE_URL as HIMALAYAS_URL
from jobscout.sources.registry import SOURCE_MISSING_CREDENTIALS
from jobscout.sources.remotive import BASE_URL as REMOTIVE_URL
from tests.conftest import load_fixture
from tests.matching.fakes import DeterministicFakeEmbedding

DIM = 8
PARAGRAPH = "Junior AI engineer, remote, Python and LangChain."
OTHER_PARAGRAPH = "Senior data engineer, Spark and dbt, hybrid in Lisbon."
TERMS = ["ai engineer", "python", "langchain", "llm", "fastapi", "nlp", "pytorch"]
# Both fixtures carry four postings, one of which is deliberately malformed.
VALID_PER_FIXTURE = 3


# --------------------------------------------------------------------------- doubles


class _Scripted:
    def __init__(self, parent: "SearchChatModel", schema: Any) -> None:
        self._parent = parent
        self._schema = schema

    def invoke(self, _messages: Any) -> Any:
        if self._schema is EvaluationResult:
            return self._parent._evaluate()
        return self._parent._extract()


class SearchChatModel:
    """One search makes two different LLM calls; this answers each by the schema asked for."""

    def __init__(
        self,
        extraction: ExtractedProfile | Exception,
        evaluation: EvaluationResult | Exception | None = None,
        on_evaluate: Any = None,
    ) -> None:
        self.extraction = extraction
        self.evaluation = evaluation or EvaluationResult(
            score=80, reasoning="Fits.", matched_skills=["Python"]
        )
        self.on_evaluate = on_evaluate
        self.extraction_calls = 0
        self.evaluation_calls = 0

    def with_structured_output(self, schema: Any) -> _Scripted:
        return _Scripted(self, schema)

    def _extract(self) -> Any:
        self.extraction_calls += 1
        if isinstance(self.extraction, Exception):
            raise self.extraction
        return self.extraction

    def _evaluate(self) -> Any:
        self.evaluation_calls += 1
        if self.on_evaluate is not None:
            self.on_evaluate(self.evaluation_calls)
        if isinstance(self.evaluation, Exception):
            raise self.evaluation
        return self.evaluation


def _extraction(terms: list[str], **fields: Any) -> ExtractedProfile:
    return ExtractedProfile(terms=terms, **fields)


def _deps(chat: SearchChatModel, threshold: float = -1.0) -> GraphDeps:
    # threshold -1.0: every job clears the cosine prefilter, so the LLM path is the one
    # under test. The prefilter has its own tests in tests/matching.
    return GraphDeps(
        chat=chat,  # type: ignore[arg-type]
        embed=DeterministicFakeEmbedding(size=DIM),  # type: ignore[arg-type]
        threshold=threshold,
        model_name="fake-model",
    )


def _settings(**kw: Any) -> Settings:
    kw.setdefault("embedding_dim", DIM)
    kw.setdefault("sources", "himalayas,remotive")
    return Settings(_env_file=None, **kw)


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def himalayas_sample() -> dict:
    return load_fixture("himalayas_search.json")


@pytest.fixture
def remotive_sample() -> dict:
    return load_fixture("remotive_search.json")


def _ok(sample: dict) -> httpx.Response:
    return httpx.Response(200, json=sample)


def _user(session: Session, paragraph: str = PARAGRAPH, **prefs: Any) -> Any:
    user = get_or_create_default_user(session)
    assert user.id is not None
    update_preferences(session, user.id, {"profile_summary": paragraph, **prefs})
    return user


def _the_run(session: Session) -> Run:
    return session.exec(select(Run)).one()


def _jobs(session: Session) -> list[Job]:
    return list(session.exec(select(Job)).all())


# --------------------------------------------------------------------------- terms


@respx.mock
def test_an_unchanged_paragraph_reuses_terms_and_makes_no_llm_call(session, himalayas_sample):
    respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    user = _user(
        session,
        PARAGRAPH,
        search_terms=["python"],
        profile_hash=profile_hash(PARAGRAPH),
    )
    chat = SearchChatModel(_extraction(["never used"]))

    result = run_search(session, _settings(sources="himalayas"), user.id, deps=_deps(chat))

    assert chat.extraction_calls == 0
    assert result.terms == ["python"]
    assert get_preferences(session, user.id).search_terms == ["python"]


@respx.mock
def test_a_changed_paragraph_re_extracts(session, himalayas_sample):
    respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    user = _user(
        session,
        PARAGRAPH,
        search_terms=["spark"],
        profile_hash=profile_hash(OTHER_PARAGRAPH),
    )
    chat = SearchChatModel(_extraction(["ai engineer", "python"]))

    result = run_search(session, _settings(sources="himalayas"), user.id, deps=_deps(chat))

    assert chat.extraction_calls == 1
    assert result.terms == ["ai engineer", "python"]
    prefs = get_preferences(session, user.id)
    assert prefs.search_terms == ["ai engineer", "python"]
    assert prefs.profile_hash == profile_hash(PARAGRAPH)


@respx.mock
def test_a_stored_hash_with_no_stored_terms_re_extracts(session, himalayas_sample):
    """A matching hash is only worth reusing when there are terms to reuse."""
    respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    user = _user(session, PARAGRAPH, search_terms=[], profile_hash=profile_hash(PARAGRAPH))
    chat = SearchChatModel(_extraction(["python"]))

    result = run_search(session, _settings(sources="himalayas"), user.id, deps=_deps(chat))

    assert chat.extraction_calls == 1
    assert result.terms == ["python"]


@respx.mock
def test_extraction_stores_the_preferences_it_found(session, himalayas_sample):
    respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    user = _user(session, PARAGRAPH)
    chat = SearchChatModel(
        _extraction(
            ["python"],
            seniority=["junior"],
            required_skills=["Python"],
            excluded_keywords=["senior"],
        )
    )

    run_search(session, _settings(sources="himalayas"), user.id, deps=_deps(chat))

    prefs = get_preferences(session, user.id)
    assert prefs.seniority == ["junior"]
    assert prefs.required_skills == ["Python"]
    assert prefs.excluded_keywords == ["senior"]


@respx.mock
def test_an_extraction_that_finds_nothing_does_not_erase_what_the_user_set(
    session, himalayas_sample
):
    """Extraction may add to the profile; it may never silently empty a field."""
    respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    user = _user(session, PARAGRAPH, required_skills=["Rust"], excluded_keywords=["staff"])
    chat = SearchChatModel(_extraction(["python"]))

    run_search(session, _settings(sources="himalayas"), user.id, deps=_deps(chat))

    prefs = get_preferences(session, user.id)
    assert prefs.required_skills == ["Rust"]
    assert prefs.excluded_keywords == ["staff"]


@respx.mock
def test_an_empty_paragraph_writes_a_failed_run_and_fetches_nothing(session):
    route = respx.get(HIMALAYAS_URL).mock(return_value=httpx.Response(200, json={"jobs": []}))
    user = _user(session, "")
    chat = SearchChatModel(_extraction(["python"]))

    result = run_search(session, _settings(sources="himalayas"), user.id, deps=_deps(chat))

    assert result.ok is False
    assert result.fetched == 0
    assert route.call_count == 0
    run = _the_run(session)
    assert (run.job, run.user_id, run.ok) == ("search", user.id, False)
    assert run.finished_at is not None
    assert run.error is not None and "nothing to search for" in run.error


# --------------------------------------------------------------------------- fetching


@respx.mock
def test_each_source_is_searched_with_the_top_terms(session, himalayas_sample, remotive_sample):
    himalayas = respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    remotive = respx.get(REMOTIVE_URL).mock(return_value=_ok(remotive_sample))
    user = _user(session)
    chat = SearchChatModel(_extraction(TERMS))

    result = run_search(session, _settings(), user.id, deps=_deps(chat))

    assert len(TERMS) > MAX_TERMS_PER_SOURCE  # the slice has something to cut
    searched = TERMS[:MAX_TERMS_PER_SOURCE]
    assert [call.request.url.params["q"] for call in himalayas.calls] == searched
    assert [call.request.url.params["search"] for call in remotive.calls] == searched
    assert result.sources_ok == 2
    assert result.fetched == 2 * VALID_PER_FIXTURE


@respx.mock
def test_a_catalogue_source_is_asked_once_with_no_keywords(session):
    """Arbeitnow ignores the query and dumps its catalogue; asking per term downloads it
    five times over."""
    sample = load_fixture("arbeitnow_sample.json")
    route = respx.get(ARBEITNOW_URL).mock(return_value=_ok(sample))
    user = _user(session)
    chat = SearchChatModel(_extraction(TERMS))

    result = run_search(
        session,
        _settings(sources="arbeitnow", arbeitnow_max_pages=1),
        user.id,
        deps=_deps(chat),
    )

    assert route.call_count == 1
    assert "q" not in route.calls[0].request.url.params
    assert result.fetched == 3


@respx.mock
def test_the_same_job_from_two_terms_is_counted_once(session, himalayas_sample):
    respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    user = _user(session)
    chat = SearchChatModel(_extraction(["python", "langchain"]))

    result = run_search(session, _settings(sources="himalayas"), user.id, deps=_deps(chat))

    assert result.fetched == VALID_PER_FIXTURE
    assert len(_jobs(session)) == VALID_PER_FIXTURE


@respx.mock
def test_one_source_failing_does_not_fail_the_run(session, remotive_sample):
    himalayas = respx.get(HIMALAYAS_URL).mock(return_value=httpx.Response(500))
    respx.get(REMOTIVE_URL).mock(return_value=_ok(remotive_sample))
    user = _user(session)
    chat = SearchChatModel(_extraction(["python", "langchain"]))

    result = run_search(session, _settings(), user.id, deps=_deps(chat))

    assert result.ok is True
    assert (result.sources_ok, result.sources_failed) == (1, 1)
    assert result.fetched == VALID_PER_FIXTURE
    assert any("himalayas" in error for error in result.errors)
    # The failing source is abandoned instead of being asked for its remaining terms.
    assert himalayas.call_count == 1
    assert _the_run(session).ok is True


@respx.mock
def test_every_source_failing_fails_the_run(session):
    respx.get(HIMALAYAS_URL).mock(return_value=httpx.Response(500))
    respx.get(REMOTIVE_URL).mock(return_value=httpx.Response(500))
    user = _user(session)
    chat = SearchChatModel(_extraction(["python"]))

    result = run_search(session, _settings(), user.id, deps=_deps(chat))

    assert result.ok is False
    assert (result.sources_ok, result.sources_failed) == (0, 2)
    assert result.fetched == 0
    assert len(result.errors) == 2
    run = _the_run(session)
    assert run.ok is False and run.error is not None


@respx.mock
def test_a_429_partway_keeps_what_was_already_fetched(session, himalayas_sample):
    """Throwing away completed work because a later call failed is the expensive mistake."""
    respx.get(HIMALAYAS_URL, params={"q": "python"}).mock(return_value=_ok(himalayas_sample))
    respx.get(HIMALAYAS_URL, params={"q": "langchain"}).mock(return_value=httpx.Response(429))
    abandoned = respx.get(HIMALAYAS_URL, params={"q": "llm"}).mock(
        return_value=_ok(himalayas_sample)
    )
    user = _user(session)
    chat = SearchChatModel(_extraction(["python", "langchain", "llm"]))

    result = run_search(session, _settings(sources="himalayas"), user.id, deps=_deps(chat))

    assert result.fetched == VALID_PER_FIXTURE
    assert len(_jobs(session)) == VALID_PER_FIXTURE
    assert abandoned.call_count == 0
    assert any("429" in error for error in result.errors)
    # It answered, so the run is ok and its failure is named rather than fatal.
    assert result.ok is True and result.sources_ok == 1


def test_a_run_with_no_usable_source_says_which_were_dormant(session, monkeypatch):
    monkeypatch.setitem(SOURCE_MISSING_CREDENTIALS, "himalayas", lambda s: ["HIMALAYAS_KEY"])
    user = _user(session)
    chat = SearchChatModel(_extraction(["python"]))

    result = run_search(session, _settings(sources="himalayas"), user.id, deps=_deps(chat))

    assert result.ok is False
    assert result.fetched == 0
    assert any("himalayas" in e and "HIMALAYAS_KEY" in e for e in result.errors)
    assert _the_run(session).ok is False


def test_a_run_with_no_source_configured_at_all_says_so(session):
    user = _user(session)
    chat = SearchChatModel(_extraction(["python"]))

    result = run_search(session, _settings(sources=""), user.id, deps=_deps(chat))

    assert result.ok is False
    assert any("no sources" in error.lower() for error in result.errors)


# --------------------------------------------------------------------------- scoring


@respx.mock
def test_scoring_covers_an_active_job_this_run_did_not_fetch(session, himalayas_sample):
    """The candidate set is every active job with no match or a stale one — not the catch."""
    respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    old = Job(
        source="t",
        external_id="old-1",
        title="AI Engineer",
        company="Acme",
        url="https://x/old-1",
        description="Python LLM systems.",
        content_hash="h-old-1",
    )
    session.add(old)
    session.commit()
    session.refresh(old)
    user = _user(session)
    chat = SearchChatModel(_extraction(["python"]))

    result = run_search(session, _settings(sources="himalayas"), user.id, deps=_deps(chat))

    assert result.candidates == VALID_PER_FIXTURE + 1
    assert result.evaluated == VALID_PER_FIXTURE + 1
    scored = session.exec(select(Match).where(Match.job_id == old.id)).one()
    assert scored.score == 80


@respx.mock
def test_a_capped_run_reports_what_remains_and_the_next_run_resumes(session, himalayas_sample):
    respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    user = _user(session)
    settings = _settings(sources="himalayas", max_llm_evaluations_per_run=1)
    chat = SearchChatModel(_extraction(["python"]))

    first = run_search(session, settings, user.id, deps=_deps(chat))

    assert (first.candidates, first.evaluated, first.remaining) == (VALID_PER_FIXTURE, 1, 2)
    assert first.ok is True
    assert _the_run(session).counters["remaining"] == 2

    second = run_search(session, settings, user.id, deps=_deps(chat))

    assert (second.candidates, second.evaluated, second.remaining) == (2, 1, 1)


@respx.mock
def test_jobs_the_prefilter_rejected_are_done_not_remaining(session, himalayas_sample):
    """`low` is terminal: those jobs are not waiting for the next run, so `remaining` is 0
    even though nothing was evaluated."""
    respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    user = _user(session)
    chat = SearchChatModel(_extraction(["python"]))

    # A threshold above 1.0 is unreachable for a cosine, so every job is prefiltered out.
    result = run_search(
        session, _settings(sources="himalayas"), user.id, deps=_deps(chat, threshold=2.0)
    )

    assert chat.evaluation_calls == 0
    assert (result.candidates, result.evaluated, result.remaining) == (VALID_PER_FIXTURE, 0, 0)
    assert result.ok is True
    assert [m.status for m in session.exec(select(Match)).all()] == ["low"] * VALID_PER_FIXTURE

    # And they really do not come back: the next run has nothing left to score.
    again = run_search(
        session, _settings(sources="himalayas"), user.id, deps=_deps(chat, threshold=2.0)
    )
    assert (again.candidates, again.remaining) == (0, 0)


@respx.mock
def test_a_run_that_evaluated_nothing_because_every_job_errored_is_not_ok(
    session, himalayas_sample
):
    respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    user = _user(session)
    chat = SearchChatModel(_extraction(["python"]), evaluation=RuntimeError("boom"))

    result = run_search(session, _settings(sources="himalayas"), user.id, deps=_deps(chat))

    assert result.sources_ok == 1  # fetching was fine; scoring was not
    assert result.evaluated == 0
    assert result.ok is False
    assert len(result.errors) == VALID_PER_FIXTURE


@respx.mock
def test_a_missing_provider_fails_the_run_instead_of_escaping_it(
    session, himalayas_sample, monkeypatch
):
    """Spec 5.3: no LLM key means the page says so, not that a background job explodes."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    user = _user(session, PARAGRAPH, search_terms=["python"], profile_hash=profile_hash(PARAGRAPH))

    result = run_search(session, _settings(sources="himalayas"), user.id, deps=None)

    assert result.ok is False
    assert any("GOOGLE_API_KEY" in error for error in result.errors)
    run = _the_run(session)
    assert run.ok is False and run.finished_at is not None


# ------------------------------------------------------- what the page sees mid-flight


def _run_against_a_file_db(tmp_path: Path, sample: dict, probe: Any) -> Any:
    """Run a search on a file-backed SQLite so a probe can read it over a second
    connection — on the in-memory database every session shares one connection and an
    uncommitted write would be indistinguishable from a committed one."""
    engine = create_engine_from_url(f"sqlite:///{tmp_path.as_posix()}/search.db")
    init_db(engine)
    with Session(engine) as session:
        user = _user(session)
        chat = SearchChatModel(_extraction(["python"]), on_evaluate=lambda n: probe(engine, n))
        return run_search(session, _settings(sources="himalayas"), user.id, deps=_deps(chat))


@respx.mock
def test_matches_are_committed_before_the_run_finishes(tmp_path, himalayas_sample):
    respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    seen: dict[int, int] = {}

    def probe(engine: Any, call: int) -> None:
        with Session(engine) as other:
            seen[call] = len(other.exec(select(Match)).all())

    result = _run_against_a_file_db(tmp_path, himalayas_sample, probe)

    assert result.evaluated == VALID_PER_FIXTURE
    # By the second evaluation the first match is durable in another connection.
    assert seen[1] == 0 and seen[2] == 1 and seen[3] == 2


@respx.mock
def test_counters_are_written_while_the_run_is_still_in_flight(tmp_path, himalayas_sample):
    respx.get(HIMALAYAS_URL).mock(return_value=_ok(himalayas_sample))
    seen: dict[str, Any] = {}

    def probe(engine: Any, call: int) -> None:
        if call != 1:
            return
        with Session(engine) as other:
            run = other.exec(select(Run)).one()
            seen["counters"] = dict(run.counters)
            seen["finished_at"] = run.finished_at

    _run_against_a_file_db(tmp_path, himalayas_sample, probe)

    assert seen["finished_at"] is None  # the run is still going
    assert seen["counters"]["fetched"] == VALID_PER_FIXTURE
    assert seen["counters"]["candidates"] == VALID_PER_FIXTURE
    assert seen["counters"]["sources_ok"] == 1

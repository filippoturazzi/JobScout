from datetime import timedelta

import pytest
from sqlmodel import select

from jobscout.config import Settings
from jobscout.matching.llm import MissingProviderError
from jobscout.matching.terms import _LLMOutput
from jobscout.models import Job, Match, Search, SearchJob, UserPreferences
from jobscout.models.base import utcnow
from jobscout.pipeline.conversation import Answer, QuestionsPendingError
from jobscout.pipeline.searches import (
    SearchNotFoundError,
    add_search,
    answer_question,
    confirm,
    conversation_of,
    create_search,
    delete_search,
    get_or_create_default_search,
    get_search,
    latest_search,
    list_searches,
    record_fetched,
    refine,
    reread,
    touch,
)
from jobscout.pipeline.users import get_or_create_default_user, get_preferences
from tests.helpers import make_search
from tests.matching.fakes import CountingChatModel


def _job(session, external_id: str = "j") -> Job:
    job = Job(
        source="t",
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        url="https://x/j",
        description="d",
        content_hash="h",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_add_search_creates_its_preferences(session):
    search = make_search(session, paragraph="AI engineer")
    assert get_preferences(session, search.id).profile_summary == "AI engineer"


def test_latest_search_is_the_most_recently_used(session):
    user = get_or_create_default_user(session)
    older = add_search(session, user.id, "older")
    newer = add_search(session, user.id, "newer")
    assert latest_search(session, user.id).id == newer.id

    older.last_used_at = utcnow() - timedelta(days=1)
    newer.last_used_at = utcnow() - timedelta(days=2)
    session.add_all([older, newer])
    session.commit()
    touch(session, newer)

    assert latest_search(session, user.id).id == newer.id
    assert [s.id for s in list_searches(session, user.id)] == [newer.id, older.id]


def test_latest_search_is_none_without_searches(session):
    user = get_or_create_default_user(session)
    assert latest_search(session, user.id) is None


def test_get_search_refuses_another_users_search(session):
    search = make_search(session)

    with pytest.raises(SearchNotFoundError):
        get_search(session, search.user_id + 1, search.id)
    with pytest.raises(SearchNotFoundError):
        get_search(session, search.user_id, search.id + 1)
    assert get_search(session, search.user_id, search.id).id == search.id


def test_delete_search_removes_its_preferences_and_matches_but_not_jobs(session):
    search = make_search(session, "keep me out")
    other = make_search(session, "stay", title="Other")
    job = _job(session)
    for s in (search, other):
        session.add(Match(job_id=job.id, user_id=s.user_id, search_id=s.id, similarity=0.5))
    record_fetched(session, search.id, [job.id])
    record_fetched(session, other.id, [job.id])
    session.commit()

    delete_search(session, search.user_id, search.id)

    assert session.get(Search, search.id) is None
    assert [p.search_id for p in session.exec(select(UserPreferences)).all()] == [other.id]
    assert [m.search_id for m in session.exec(select(Match)).all()] == [other.id]
    assert [r.search_id for r in session.exec(select(SearchJob)).all()] == [other.id]
    assert session.exec(select(Job)).one().id == job.id


def test_get_or_create_default_search_reuses_the_latest(session):
    user = get_or_create_default_user(session)

    first = get_or_create_default_search(session, user.id)
    second = get_or_create_default_search(session, user.id)

    assert first.id == second.id
    assert len(session.exec(select(Search)).all()) == 1


def test_default_user_has_no_preferences_until_a_search_exists(session):
    user = get_or_create_default_user(session)
    assert session.exec(select(UserPreferences)).all() == []

    add_search(session, user.id, "first")

    assert len(session.exec(select(UserPreferences)).all()) == 1


def test_record_fetched_is_idempotent(session):
    s = make_search(session)
    j1, j2 = _job(session, "j1"), _job(session, "j2")
    assert record_fetched(session, s.id, [j1.id, j2.id]) == 2
    assert record_fetched(session, s.id, [j2.id]) == 0
    assert len(session.exec(select(SearchJob)).all()) == 2


PARAGRAPH = "Junior AI engineer, remote from Portugal, Python and LangChain."


def _settings(**kw) -> Settings:
    kw.setdefault("llm_provider", "ollama")
    return Settings(_env_file=None, **kw)


def _reading(**kw) -> _LLMOutput:
    fields = {
        "terms": ["ai engineer"],
        "seniority": ["junior"],
        "required_skills": ["Python"],
        "stated_work_modes": ["remote"],
        "stated_regions": ["Portugal"],
    }
    return _LLMOutput(**{**fields, **kw})


def _create(session, chat=None, paragraph=PARAGRAPH):
    user = get_or_create_default_user(session)
    chat = chat or CountingChatModel(results=[_reading()])
    return create_search(session, _settings(), user.id, paragraph, chat), chat


def test_create_search_reads_the_paragraph_once_and_titles_it(session):
    search, chat = _create(session)

    assert chat.calls == 1
    assert search.title == "Junior AI Engineer"
    assert conversation_of(search).reading.terms == ["ai engineer"]


def test_create_search_writes_no_preferences(session):
    search, _ = _create(session)

    prefs = get_preferences(session, search.id)
    assert prefs.search_terms == []
    assert prefs.profile_summary == PARAGRAPH


def test_create_search_without_a_key_writes_nothing(session):
    user = get_or_create_default_user(session)
    chat = CountingChatModel(results=[_reading()])

    with pytest.raises(MissingProviderError):
        create_search(
            session, _settings(llm_provider="google", google_api_key=None), user.id, "x", chat
        )

    assert session.exec(select(Search)).all() == []
    assert chat.calls == 0


def test_create_search_refuses_a_blank_paragraph(session):
    user = get_or_create_default_user(session)
    with pytest.raises(ValueError):
        create_search(session, _settings(), user.id, "   ", CountingChatModel(results=[_reading()]))
    assert session.exec(select(Search)).all() == []


def test_a_failed_reading_keeps_the_search_and_its_paragraph(session):
    search, _ = _create(session, CountingChatModel(error=RuntimeError("quota")))

    c = conversation_of(search)
    assert c.reading_error == "RuntimeError: quota"
    assert c.reading is None
    assert c.paragraph == PARAGRAPH
    assert search.title == "Junior AI engineer, remote from Portugal,"
    assert get_preferences(session, search.id).profile_summary == PARAGRAPH


def test_reread_clears_the_error(session):
    search, chat = _create(session, CountingChatModel(error=RuntimeError("quota")))
    chat.error = None
    chat.results = [_reading()]

    search = reread(session, search.user_id, search.id, chat)

    c = conversation_of(search)
    assert c.reading_error is None and c.reading.terms == ["ai engineer"]


def test_refine_keeps_answers_and_reads_the_whole_text(session):
    seen = []
    search, chat = _create(session, CountingChatModel(results=[_reading(seniority=[])]))
    search = answer_question(session, search.user_id, search.id, "level", Answer(choice="senior"))
    original = chat.with_structured_output

    def spy(schema):
        runnable = original(schema)
        invoke = runnable.invoke
        runnable.invoke = lambda messages: (seen.append(messages), invoke(messages))[1]
        return runnable

    chat.with_structured_output = spy

    search = refine(session, search.user_id, search.id, "Also Rust.", chat)

    text = seen[0][1].content
    assert PARAGRAPH in text and "Also Rust." in text
    c = conversation_of(search)
    assert c.refinements == ["Also Rust."]
    assert c.answers["level"].choice == "senior"


def test_confirm_writes_the_summary_as_preferences(session):
    search, _ = _create(session)

    prefs = confirm(session, _settings(), search.user_id, search.id)

    assert prefs.search_terms == ["ai engineer"]
    assert prefs.seniority == ["junior"]
    assert prefs.work_modes == ["remote"]
    assert prefs.regions == ["Portugal"]
    assert prefs.required_skills == ["Python"]
    assert conversation_of(get_search(session, search.user_id, search.id)).confirmed is True


def test_confirm_refuses_with_questions_pending(session):
    search, _ = _create(session, CountingChatModel(results=[_reading(seniority=[])]))

    with pytest.raises(QuestionsPendingError):
        confirm(session, _settings(), search.user_id, search.id)

    assert get_preferences(session, search.id).search_terms == []


def test_confirm_stales_only_this_searchs_matches(session):
    search, _ = _create(session)
    other = make_search(session, "other", title="Other")
    job = _job(session)
    for s in (search, other):
        session.add(Match(job_id=job.id, user_id=s.user_id, search_id=s.id, similarity=0.5))
    session.commit()

    confirm(session, _settings(), search.user_id, search.id)

    statuses = {m.search_id: m.status for m in session.exec(select(Match)).all()}
    assert statuses == {search.id: "stale", other.id: "new"}

import pytest
from sqlmodel import select

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps
from jobscout.matching.prompts import job_text, profile_text
from jobscout.matching.schemas import EvaluationResult
from jobscout.matching.vectors import cosine
from jobscout.models import Job, Match
from jobscout.pipeline.matching import run_match, select_candidates
from jobscout.pipeline.users import get_or_create_default_user, get_preferences, update_preferences
from tests.matching.fakes import CountingChatModel, DeterministicFakeEmbedding

DIM = 8


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _deps(chat: CountingChatModel, threshold: float = -1.0) -> GraphDeps:
    return GraphDeps(
        chat=chat,  # type: ignore[arg-type]
        embed=DeterministicFakeEmbedding(size=DIM),  # type: ignore[arg-type]
        threshold=threshold,
        model_name="fake-model",
    )


def _add_job(session, external_id: str, title: str = "AI Engineer") -> Job:
    job = Job(
        source="t",
        external_id=external_id,
        title=title,
        company="Acme",
        location="Berlin, Germany",
        remote=True,
        url=f"https://x/{external_id}",
        description=f"{title} building Python LLM systems.",
        content_hash=f"h-{external_id}",
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _user_with_profile(session):
    user = get_or_create_default_user(session)
    update_preferences(
        session,
        user.id,
        {"titles": ["AI Engineer"], "profile_summary": "Python LLM engineer."},
    )
    return user


def test_no_profile_summary_evaluates_nothing(session):
    user = get_or_create_default_user(session)
    _add_job(session, "a")
    result = run_match(session, _settings(), user.id, deps=_deps(CountingChatModel()))
    assert result.evaluated == 0
    assert result.error is not None and "profile" in result.error.lower()


def test_evaluates_candidates_and_persists_matches(session):
    user = _user_with_profile(session)
    job = _add_job(session, "a")
    chat = CountingChatModel(
        results=[EvaluationResult(score=88, reasoning="Fits.", matched_skills=["Python"])]
    )

    result = run_match(session, _settings(), user.id, deps=_deps(chat))

    assert (result.evaluated, chat.calls) == (1, 1)
    match = session.exec(select(Match)).one()
    assert match.job_id == job.id and match.user_id == user.id
    assert match.score == 88 and match.status == "new"
    assert match.matched_skills == ["Python"] and match.llm_model == "fake-model"
    fake = DeterministicFakeEmbedding(size=DIM)
    expected = cosine(
        fake.embed_query(job_text(job)),
        fake.embed_query(profile_text(get_preferences(session, user.id))),
    )
    assert match.similarity == pytest.approx(expected)
    session.refresh(job)
    assert job.embedding is not None, "the job embedding must be cached"


def test_below_threshold_writes_low_without_calling_the_llm(session):
    user = _user_with_profile(session)
    _add_job(session, "a")
    chat = CountingChatModel()

    result = run_match(session, _settings(), user.id, deps=_deps(chat, threshold=1.1))

    assert chat.calls == 0
    assert (result.evaluated, result.skipped_low) == (0, 1)
    match = session.exec(select(Match)).one()
    assert match.status == "low" and match.score is None


def test_second_run_is_idempotent(session):
    user = _user_with_profile(session)
    _add_job(session, "a")
    chat = CountingChatModel()
    run_match(session, _settings(), user.id, deps=_deps(chat))

    second = run_match(session, _settings(), user.id, deps=_deps(chat))

    assert second.evaluated == 0 and chat.calls == 1
    assert len(session.exec(select(Match)).all()) == 1


def test_cap_limits_evaluations_and_takes_the_best_first(session):
    user = _user_with_profile(session)
    for i in range(5):
        _add_job(session, f"j{i}")
    chat = CountingChatModel()

    result = run_match(session, _settings(max_llm_evaluations_per_run=2), user.id, deps=_deps(chat))

    assert (result.evaluated, chat.calls) == (2, 2)
    evaluated = session.exec(select(Match)).all()
    assert len(evaluated) == 2
    remaining = [
        job
        for job in session.exec(select(Job)).all()
        if job.id not in {m.job_id for m in evaluated}
    ]
    assert len(remaining) == 3, "unselected candidates keep no row"


def test_stale_is_reevaluated_and_dismissed_is_not(session):
    user = _user_with_profile(session)
    stale_job = _add_job(session, "stale-one")
    dismissed_job = _add_job(session, "dismissed-one")
    session.add(Match(job_id=stale_job.id, user_id=user.id, similarity=0.9, status="stale"))
    session.add(Match(job_id=dismissed_job.id, user_id=user.id, similarity=0.9, status="dismissed"))
    session.commit()
    chat = CountingChatModel()

    result = run_match(session, _settings(), user.id, deps=_deps(chat))

    assert result.evaluated == 1
    refreshed = {m.job_id: m for m in session.exec(select(Match)).all()}
    assert refreshed[stale_job.id].status == "new"
    assert refreshed[dismissed_job.id].status == "dismissed"


def test_dry_run_previews_without_calling_the_llm(session):
    user = _user_with_profile(session)
    _add_job(session, "a")
    chat = CountingChatModel()

    result = run_match(session, _settings(), user.id, dry_run=True, deps=_deps(chat))

    assert chat.calls == 0 and result.evaluated == 0
    assert len(result.previewed) == 1
    assert session.exec(select(Match)).all() == []


def test_llm_failure_is_isolated(session):
    user = _user_with_profile(session)
    _add_job(session, "a")
    _add_job(session, "b")
    chat = CountingChatModel(error=RuntimeError("rate limited"))

    result = run_match(session, _settings(), user.id, deps=_deps(chat))

    assert result.evaluated == 0
    assert len(result.errors) == 2 and "rate limited" in result.errors[0]
    assert session.exec(select(Match)).all() == []


def test_commit_failure_is_counted_as_an_error_not_a_success(session, monkeypatch):
    user = _user_with_profile(session)
    _add_job(session, "a")
    chat = CountingChatModel()
    original_commit = session.commit
    calls = {"n": 0}

    def flaky_commit() -> None:
        calls["n"] += 1
        # Calls 1 and 2 are the profile- and job-embedding caching commits inside
        # run_match, which happen before the per-job loop; only the 3rd commit — the
        # one after _upsert_match for this single candidate — should fail.
        if calls["n"] == 3:
            raise RuntimeError("disk full")
        original_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)

    result = run_match(session, _settings(), user.id, deps=_deps(chat))

    assert result.evaluated == 0 and result.skipped_low == 0
    assert len(result.errors) == 1 and "disk full" in result.errors[0]


def test_select_candidates_applies_the_deterministic_filter(session):
    user = _user_with_profile(session)
    _add_job(session, "good", title="AI Engineer")
    _add_job(session, "bad", title="Data Analyst")

    candidates = select_candidates(session, get_preferences(session, user.id), user.id)

    assert [job.external_id for job in candidates] == ["good"]


def test_dry_run_never_builds_the_chat_client(session, monkeypatch):
    import jobscout.pipeline.matching as matching_module

    user = _user_with_profile(session)
    _add_job(session, "a")

    def _explode(_settings):
        raise AssertionError("dry run must not construct a chat model")

    monkeypatch.setattr(matching_module, "chat_model", _explode)
    monkeypatch.setattr(
        matching_module, "embeddings", lambda _settings: DeterministicFakeEmbedding(size=DIM)
    )

    result = run_match(session, _settings(), user.id, dry_run=True)

    assert len(result.previewed) == 1


def test_missing_provider_surfaces_as_error(session, monkeypatch):
    user = _user_with_profile(session)
    _add_job(session, "a")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(Exception, match="GOOGLE_API_KEY"):
        run_match(session, _settings(), user.id)  # no deps -> real factory


def test_embedding_work_is_bounded_per_run(session):
    user = _user_with_profile(session)
    for i in range(5):
        _add_job(session, f"j{i}")

    result = run_match(
        session, _settings(max_embeddings_per_run=2), user.id, deps=_deps(CountingChatModel())
    )

    assert result.embedded == 2
    assert result.embeddings_pending == 3
    assert result.evaluated <= 2, "only embedded candidates can be ranked and evaluated"


def test_later_runs_pick_up_the_remaining_embeddings(session):
    user = _user_with_profile(session)
    for i in range(3):
        _add_job(session, f"j{i}")
    settings = _settings(max_embeddings_per_run=1)

    run_match(session, settings, user.id, deps=_deps(CountingChatModel()))
    second = run_match(session, settings, user.id, deps=_deps(CountingChatModel()))

    assert second.embedded == 1, "the next run embeds the next batch"

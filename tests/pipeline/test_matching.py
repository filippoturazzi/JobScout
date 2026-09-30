import logging

import pytest
from sqlmodel import select

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps
from jobscout.matching.prompts import job_embedding_text, profile_text
from jobscout.matching.schemas import EvaluationResult
from jobscout.matching.vectors import cosine, dim, pack
from jobscout.models import Job, Match
from jobscout.pipeline.matching import run_match, select_candidates
from jobscout.pipeline.users import get_or_create_default_user, get_preferences, update_preferences
from tests.matching.fakes import CountingChatModel, DeterministicFakeEmbedding

DIM = 8


def _settings(**kw) -> Settings:
    # The fakes return DIM-dimensional vectors; saying so keeps the profile-embedding
    # cache live in tests instead of re-embedding on every run.
    kw.setdefault("embedding_dim", DIM)
    return Settings(_env_file=None, **kw)


def _deps(
    chat: CountingChatModel,
    threshold: float = -1.0,
    embed: DeterministicFakeEmbedding | None = None,
) -> GraphDeps:
    return GraphDeps(
        chat=chat,  # type: ignore[arg-type]
        embed=embed or DeterministicFakeEmbedding(size=DIM),  # type: ignore[arg-type]
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
        fake.embed_query(job_embedding_text(job)),
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


def test_cap_limits_evaluations_and_takes_the_highest_similarities(session):
    user = _user_with_profile(session)
    # Deliberately different texts, so the five jobs get five different cosines and
    # "the cap kept the best two" is distinguishable from "the cap kept any two".
    titles = [
        "AI Engineer",
        "Senior AI Engineer",
        "Junior AI Engineer",
        "Staff AI Engineer",
        "Lead AI Engineer",
    ]
    jobs = [_add_job(session, f"j{i}", title=title) for i, title in enumerate(titles)]
    fake = DeterministicFakeEmbedding(size=DIM)
    profile_vector = fake.embed_query(profile_text(get_preferences(session, user.id)))
    similarities = {
        job.id: cosine(fake.embed_query(job_embedding_text(job)), profile_vector) for job in jobs
    }
    assert len(set(similarities.values())) == 5, "the fixture must not produce ties"
    best_two = {
        job_id for job_id, _ in sorted(similarities.items(), key=lambda kv: kv[1], reverse=True)[:2]
    }
    chat = CountingChatModel()

    result = run_match(session, _settings(max_llm_evaluations_per_run=2), user.id, deps=_deps(chat))

    assert (result.evaluated, chat.calls) == (2, 2)
    evaluated = session.exec(select(Match)).all()
    assert len(evaluated) == 2, "unselected candidates keep no row"
    assert {m.job_id for m in evaluated} == best_two
    assert all(m.similarity == pytest.approx(similarities[m.job_id]) for m in evaluated)


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


def test_a_failing_chunk_keeps_the_embeddings_already_paid_for(session, monkeypatch):
    """Chunk N+1 blowing up (a 429, typically) must not discard chunk N's vectors."""
    import jobscout.pipeline.matching as matching_module

    class FailsOnTheSecondBatch(DeterministicFakeEmbedding):
        def __init__(self, size: int) -> None:
            super().__init__(size)
            self.batches = 0

        def embed_documents(self, texts):
            self.batches += 1
            if self.batches == 2:
                raise RuntimeError("429 RESOURCE_EXHAUSTED")
            return super().embed_documents(texts)

    user = _user_with_profile(session)
    for i in range(4):
        _add_job(session, f"j{i}")
    monkeypatch.setattr(matching_module, "_EMBED_CHUNK", 2)
    embed = FailsOnTheSecondBatch(size=DIM)
    deps = GraphDeps(
        chat=CountingChatModel(),  # type: ignore[arg-type]
        embed=embed,  # type: ignore[arg-type]
        threshold=-1.0,
        model_name="fake-model",
    )

    with pytest.raises(RuntimeError, match="429"):
        run_match(session, _settings(), user.id, deps=deps)

    session.rollback()
    cached = [job for job in session.exec(select(Job)).all() if job.embedding is not None]
    assert len(cached) == 2, "the first chunk was committed before the second one failed"


def test_vectors_of_the_wrong_dimension_are_re_embedded(session):
    """The upgrade path of every existing install: EMBEDDING_DIM changed under stored blobs."""
    user = _user_with_profile(session)
    job = _add_job(session, "a")
    prefs = get_preferences(session, user.id)
    stale_blob = pack([0.0] * 16)
    job.embedding = stale_blob
    prefs.profile_embedding = stale_blob
    session.add(job)
    session.add(prefs)
    session.commit()

    result = run_match(
        session, _settings(embedding_dim=DIM), user.id, deps=_deps(CountingChatModel())
    )

    assert result.embedded == 1
    session.refresh(job)
    session.refresh(prefs)
    assert job.embedding is not None and dim(job.embedding) == DIM
    assert prefs.profile_embedding is not None and dim(prefs.profile_embedding) == DIM


def test_a_provider_dimension_mismatch_warns_once_per_run(session, caplog):
    """Providers that ignore output_dimensionality re-embed the profile on every run."""
    user = _user_with_profile(session)
    _add_job(session, "a")

    with caplog.at_level(logging.WARNING, logger="jobscout.pipeline.matching"):
        run_match(session, _settings(embedding_dim=768), user.id, deps=_deps(CountingChatModel()))

    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "EMBEDDING_DIM" in message and "768" in message and str(DIM) in message


def test_later_runs_pick_up_the_remaining_embeddings(session):
    user = _user_with_profile(session)
    for i in range(3):
        _add_job(session, f"j{i}")
    settings = _settings(max_embeddings_per_run=1)

    run_match(session, settings, user.id, deps=_deps(CountingChatModel()))
    second = run_match(session, settings, user.id, deps=_deps(CountingChatModel()))

    assert second.embedded == 1, "the next run embeds the next batch"


def test_a_cached_profile_embedding_is_not_recomputed_on_the_next_run(session):
    """The profile vector is paid for once; only the jobs are embedded again."""
    user = _user_with_profile(session)
    for i in range(2):
        _add_job(session, f"j{i}")
    embed = DeterministicFakeEmbedding(size=DIM)
    settings = _settings(max_embeddings_per_run=1)

    run_match(session, settings, user.id, deps=_deps(CountingChatModel(), embed=embed))
    assert embed.query_calls == 1, "the first run has to embed the profile"

    run_match(session, settings, user.id, deps=_deps(CountingChatModel(), embed=embed))

    assert embed.query_calls == 1, "the second run must reuse the stored profile vector"
    assert embed.document_calls == 2, "but it still embeds the job left over from run one"


def test_run_match_logs_the_similarity_distribution(session, caplog):
    """Stage 4 calibrates SIMILARITY_THRESHOLD from this; 0.45 is currently inert."""
    user = _user_with_profile(session)
    for i in range(3):
        _add_job(session, f"j{i}")

    with caplog.at_level(logging.INFO, logger="jobscout.pipeline.matching"):
        run_match(session, _settings(), user.id, deps=_deps(CountingChatModel()))

    assert any("similarity" in record.message for record in caplog.records)

from datetime import timedelta

import pytest
from sqlmodel import select

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps
from jobscout.matching.llm import MissingProviderError
from jobscout.models import Job, Match
from jobscout.models.base import utcnow
from jobscout.pipeline.backfill import backfill_matches
from jobscout.pipeline.run import _BACKFILL_EVALUATION_CAP, save_preferences
from jobscout.pipeline.users import get_or_create_default_user, update_preferences
from tests.matching.fakes import CountingChatModel, DeterministicFakeEmbedding

DIM = 8


def _settings(**kw) -> Settings:
    # The fakes return DIM-dimensional vectors; saying so keeps the profile-embedding
    # cache live in tests instead of re-embedding on every run.
    kw.setdefault("embedding_dim", DIM)
    return Settings(_env_file=None, **kw)


def _deps(chat: CountingChatModel) -> GraphDeps:
    return GraphDeps(
        chat=chat,  # type: ignore[arg-type]
        embed=DeterministicFakeEmbedding(size=DIM),  # type: ignore[arg-type]
        threshold=-1.0,
        model_name="fake-model",
    )


def _add_job(session, external_id: str, days_ago: int = 0) -> Job:
    seen = utcnow() - timedelta(days=days_ago)
    job = Job(
        source="t",
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        remote=True,
        url=f"https://x/{external_id}",
        description="Python LLM work.",
        content_hash=f"h-{external_id}",
        first_seen_at=seen,
        last_seen_at=seen,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_backfill_only_covers_the_window(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    _add_job(session, "recent", days_ago=1)
    _add_job(session, "ancient", days_ago=99)
    chat = CountingChatModel()

    result = backfill_matches(session, _settings(), user.id, window_days=30, deps=_deps(chat))

    assert result.evaluated == 1
    matched_ids = {m.job_id for m in session.exec(select(Match)).all()}
    recent = session.exec(select(Job).where(Job.external_id == "recent")).one()
    assert matched_ids == {recent.id}


def test_save_preferences_stales_and_backfills(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    job = _add_job(session, "a")
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, score=50, status="new"))
    session.commit()
    chat = CountingChatModel()

    prefs, run = save_preferences(
        session,
        _settings(),
        user.id,
        {"required_skills": ["Python"]},
        deps=_deps(chat),
    )

    assert prefs.required_skills == ["Python"]
    assert run.evaluated == 1, "the staled match was re-evaluated"
    assert session.exec(select(Match)).one().status == "new"


def test_save_preferences_caps_the_backfill_so_the_request_stays_interactive(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    for i in range(_BACKFILL_EVALUATION_CAP + 2):
        _add_job(session, f"j{i}")
    chat = CountingChatModel()

    _, run = save_preferences(
        session, _settings(), user.id, {"titles": ["AI Engineer"]}, deps=_deps(chat)
    )

    assert run.candidates == _BACKFILL_EVALUATION_CAP + 2
    assert (run.evaluated, chat.calls) == (_BACKFILL_EVALUATION_CAP, _BACKFILL_EVALUATION_CAP)


def test_save_preferences_ignores_irrelevant_changes(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    job = _add_job(session, "a")
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, score=50, status="seen"))
    session.commit()
    chat = CountingChatModel()

    _, run = save_preferences(
        session, _settings(), user.id, {"min_score_to_notify": 90}, deps=_deps(chat)
    )

    assert (run.evaluated, chat.calls) == (0, 0)
    assert session.exec(select(Match)).one().status == "seen"


def test_save_preferences_never_stales_dismissed(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    job = _add_job(session, "a")
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, status="dismissed"))
    session.commit()
    chat = CountingChatModel()

    _, run = save_preferences(
        session, _settings(), user.id, {"titles": ["AI Engineer"]}, deps=_deps(chat)
    )

    assert run.evaluated == 0
    assert session.exec(select(Match)).one().status == "dismissed"


def test_save_preferences_survives_a_missing_provider(session, monkeypatch):
    import jobscout.pipeline.matching as matching_module
    from jobscout.matching.llm import MissingProviderError

    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    _add_job(session, "a")

    def _no_provider(_settings):
        raise MissingProviderError("GOOGLE_API_KEY is not set.")

    monkeypatch.setattr(matching_module, "embeddings", _no_provider)

    prefs, run = save_preferences(session, _settings(), user.id, {"titles": ["AI Engineer"]})

    assert prefs.titles == ["AI Engineer"]
    assert run.error is not None and "GOOGLE_API_KEY" in run.error


def test_save_preferences_survives_a_provider_runtime_error(session, monkeypatch):
    """A 429/network/auth failure must not lose a preference save that already committed."""
    import jobscout.pipeline.matching as matching_module

    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    _add_job(session, "a")

    def _rate_limited(_settings):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(matching_module, "embeddings", _rate_limited)

    prefs, run = save_preferences(session, _settings(), user.id, {"titles": ["AI Engineer"]})

    assert prefs.titles == ["AI Engineer"]
    assert run.error == "RuntimeError: 429 RESOURCE_EXHAUSTED"


@pytest.mark.parametrize(
    "error",
    [RuntimeError("429 RESOURCE_EXHAUSTED"), MissingProviderError("no key")],
    ids=["runtime", "missing_provider"],
)
def test_save_preferences_discards_what_a_failed_backfill_left_pending(session, monkeypatch, error):
    """A failed backfill must not leave half-written rows for the next commit to flush."""
    import jobscout.pipeline.run as run_module

    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    job = _add_job(session, "a")

    def _dirty_then_fail(session_arg, *_args, **_kwargs):
        session_arg.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, score=90))
        raise error

    monkeypatch.setattr(run_module, "backfill_matches", _dirty_then_fail)

    _prefs, run = save_preferences(session, _settings(), user.id, {"titles": ["AI Engineer"]})

    assert run.error
    # Unrelated later work on the same session must not persist the abandoned row.
    session.commit()
    assert session.exec(select(Match)).all() == []


def test_save_preferences_never_spends_more_than_the_operator_allowed(session):
    """The interactive cap is a ceiling, not a floor: a lower operator budget still wins."""
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    for i in range(_BACKFILL_EVALUATION_CAP + 2):
        _add_job(session, f"j{i}")
    chat = CountingChatModel()

    _, run = save_preferences(
        session,
        _settings(max_llm_evaluations_per_run=1),
        user.id,
        {"titles": ["AI Engineer"]},
        deps=_deps(chat),
    )

    assert (run.evaluated, chat.calls) == (1, 1)

from datetime import timedelta

from sqlmodel import select

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps
from jobscout.models import Job, Match
from jobscout.models.base import utcnow
from jobscout.pipeline.backfill import backfill_matches
from jobscout.pipeline.run import save_preferences
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


def test_save_preferences_stales_without_evaluating_anything(session):
    """Matching moved to the scheduler: a save must not call a provider at all."""
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    job = _add_job(session, "a")
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, score=50, status="seen"))
    session.commit()
    chat = CountingChatModel()

    _, run = save_preferences(
        session, _settings(), user.id, {"titles": ["AI Engineer"]}, deps=_deps(chat)
    )

    assert chat.calls == 0
    assert run.evaluated == 0
    assert session.exec(select(Match)).one().status == "stale"


def test_save_preferences_wakes_the_scheduler(session):
    user = get_or_create_default_user(session)
    woken = []

    save_preferences(
        session,
        _settings(),
        user.id,
        {"profile_summary": "Python LLM engineer."},
        on_changed=lambda: woken.append(True),
    )

    assert woken == [True]


def test_save_preferences_does_not_wake_on_an_irrelevant_change(session):
    user = get_or_create_default_user(session)
    update_preferences(session, user.id, {"profile_summary": "Python LLM engineer."})
    woken = []

    save_preferences(
        session,
        _settings(),
        user.id,
        {"min_score_to_notify": 80},
        on_changed=lambda: woken.append(True),
    )

    assert woken == []


def test_save_preferences_survives_a_failing_wake(session):
    """A broken scheduler must not lose a preference save."""
    user = get_or_create_default_user(session)

    def _boom() -> None:
        raise RuntimeError("scheduler is down")

    prefs, run = save_preferences(
        session, _settings(), user.id, {"profile_summary": "Python."}, on_changed=_boom
    )

    assert prefs.profile_summary == "Python."
    assert run.error == "RuntimeError: scheduler is down"


def test_save_preferences_leaves_no_pending_rows_when_the_hook_fails(session):
    """A caller-supplied hook must not be able to leave half-written rows behind.

    `on_changed` is arbitrary caller code. If it dirties the session and then raises,
    the next commit on that session — an unrelated request — would flush its leftovers.
    """
    user = get_or_create_default_user(session)
    job = _add_job(session, "a")

    def _dirty_then_fail() -> None:
        session.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, score=90))
        raise RuntimeError("scheduler is down")

    _prefs, run = save_preferences(
        session, _settings(), user.id, {"profile_summary": "Python."}, on_changed=_dirty_then_fail
    )

    assert run.error == "RuntimeError: scheduler is down"
    session.commit()
    assert session.exec(select(Match)).all() == []

from sqlmodel import Session, select

from jobscout.models import Job, Match
from jobscout.pipeline.ingest import content_hash
from jobscout.pipeline.repair import repair_descriptions
from jobscout.pipeline.users import get_or_create_default_user

# An escaped body with the board's own unescaped footer appended — the shape that slipped
# past the old double-encoding guard and was stored as visible markup.
MIXED = (
    "&lt;p&gt;Python and LLM work.&lt;/p&gt;<p>Find more on <a href='https://x'>the board</a></p>"
)
CLEAN = "Python and LLM work. Find more on the board"
DIRTY = "<p>Python and LLM work.</p> Find more"


def _add_job(session: Session, external_id: str, description: str, raw_description: str) -> Job:
    job = Job(
        source="t",
        external_id=external_id,
        title="AI Engineer",
        company="Acme",
        remote=True,
        url=f"https://x/{external_id}",
        description=description,
        content_hash=content_hash("AI Engineer", description),
        embedding=b"\x00\x00\x00\x00",
        raw={"description": raw_description},
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def test_repair_rewrites_a_description_that_kept_its_markup(session: Session):
    job = _add_job(session, "a", DIRTY, MIXED)

    stats = repair_descriptions(session)

    session.refresh(job)
    assert stats.repaired == 1
    assert job.description == CLEAN


def test_repair_clears_the_embedding_it_invalidates(session: Session):
    """A vector computed from polluted text is worse than no vector: it is not comparable."""
    job = _add_job(session, "a", DIRTY, MIXED)

    repair_descriptions(session)

    session.refresh(job)
    assert job.embedding is None


def test_repair_recomputes_the_content_hash(session: Session):
    job = _add_job(session, "a", DIRTY, MIXED)

    repair_descriptions(session)

    session.refresh(job)
    assert job.content_hash == content_hash("AI Engineer", CLEAN)


def test_repair_stales_matches_but_never_a_dismissal(session: Session):
    user = get_or_create_default_user(session)
    job = _add_job(session, "a", DIRTY, MIXED)
    other = _add_job(session, "b", DIRTY, MIXED)
    session.add(Match(job_id=job.id, user_id=user.id, similarity=0.9, score=80, status="notified"))
    session.add(
        Match(job_id=other.id, user_id=user.id, similarity=0.4, score=10, status="dismissed")
    )
    session.commit()

    repair_descriptions(session)

    by_job = {m.job_id: m.status for m in session.exec(select(Match)).all()}
    assert by_job[job.id] == "stale"
    assert by_job[other.id] == "dismissed", "a user's own no survives a text repair"


def test_repair_leaves_already_clean_descriptions_alone(session: Session):
    """Idempotent: the second run must be a no-op, and must not clear a good embedding."""
    job = _add_job(session, "a", CLEAN, MIXED)

    stats = repair_descriptions(session)

    session.refresh(job)
    assert stats.repaired == 0
    assert stats.unchanged == 1
    assert job.embedding is not None, "nothing changed, so the vector is still valid"


def test_repair_skips_jobs_with_no_stored_payload(session: Session):
    """Nothing to reprocess from: leave the row exactly as it is rather than blanking it."""
    job = Job(
        source="t",
        external_id="a",
        title="AI Engineer",
        company="Acme",
        remote=True,
        url="https://x/a",
        description="<p>kept</p>",
        content_hash="h",
        raw={},
    )
    session.add(job)
    session.commit()

    stats = repair_descriptions(session)

    session.refresh(job)
    assert stats.skipped == 1
    assert job.description == "<p>kept</p>"

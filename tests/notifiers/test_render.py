from jobscout.models import Job, Match
from jobscout.notifiers.email import render_digest


def _row(score: int, title: str, company: str = "Acme", remote: bool = True) -> tuple[Match, Job]:
    job = Job(
        source="t",
        external_id=title,
        title=title,
        company=company,
        location="Berlin",
        remote=remote,
        url=f"https://x/{title}",
        description="d",
        content_hash="h",
    )
    match = Match(
        job_id=1,
        user_id=1,
        similarity=0.8,
        score=score,
        reasoning="Strong overlap on Python.",
        missing_skills=["Kubernetes"],
    )
    return match, job


def test_subject_counts_what_is_in_this_message():
    subject, _ = render_digest([_row(88, "AI Engineer"), _row(81, "ML Engineer")], held_back=0)

    assert subject == "JobScout: 2 new matches"


def test_subject_is_singular_for_one_match():
    subject, _ = render_digest([_row(88, "AI Engineer")], held_back=0)

    assert subject == "JobScout: 1 new match"


def test_body_carries_score_title_company_reasoning_and_link():
    _, body = render_digest([_row(88, "AI Engineer")], held_back=0)

    assert "[88]" in body
    assert "AI Engineer" in body
    assert "Acme" in body
    assert "Strong overlap on Python." in body
    assert "https://x/AI Engineer" in body


def test_body_shows_remote_or_the_location():
    _, remote_body = render_digest([_row(88, "A", remote=True)], held_back=0)
    _, onsite_body = render_digest([_row(88, "B", remote=False)], held_back=0)

    assert "remote" in remote_body
    assert "Berlin" in onsite_body


def test_body_names_what_was_held_back():
    """The cap is invisible otherwise, and a silently truncated digest reads complete."""
    _, body = render_digest([_row(88, "A")], held_back=7)

    assert "7 more" in body


def test_body_says_nothing_about_held_back_when_nothing_was():
    _, body = render_digest([_row(88, "A")], held_back=0)

    assert "more" not in body.lower().split("\n")[-1]


def test_missing_skills_appear_when_present_and_are_omitted_when_not():
    match, job = _row(88, "A")
    _, with_gap = render_digest([(match, job)], held_back=0)
    match.missing_skills = []
    _, without_gap = render_digest([(match, job)], held_back=0)

    assert "Kubernetes" in with_gap
    assert "Missing" not in without_gap

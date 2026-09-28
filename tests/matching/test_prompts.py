from jobscout.matching.prompts import (
    MAX_DESCRIPTION_CHARS,
    SYSTEM_PROMPT,
    build_user_prompt,
    job_embedding_text,
    job_text,
    profile_text,
)
from jobscout.models import Job, UserPreferences


def _prefs() -> UserPreferences:
    return UserPreferences(
        user_id=1,
        titles=["AI Engineer"],
        seniority=["junior"],
        required_skills=["Python"],
        nice_to_have_skills=["LangGraph"],
        regions=["Germany"],
        work_modes=["remote"],
        min_salary=60000,
        profile_summary="Junior AI engineer, Python, building LLM apps.",
    )


def _job(description="Build LLM pipelines in Python.") -> Job:
    return Job(
        source="arbeitnow",
        external_id="x",
        title="AI Engineer",
        company="Acme",
        location="Berlin, Germany",
        remote=True,
        url="https://x/1",
        description=description,
        tags=["python", "llm"],
        content_hash="h",
    )


def test_profile_text_includes_summary_and_preferences():
    text = profile_text(_prefs())
    assert "Junior AI engineer" in text
    assert "AI Engineer" in text and "Python" in text and "LangGraph" in text
    assert "Germany" in text and "remote" in text


def test_job_text_includes_metadata_and_truncates_description():
    text = job_text(_job(description="x" * (MAX_DESCRIPTION_CHARS + 500)))
    assert "AI Engineer" in text and "Acme" in text and "Berlin" in text and "python" in text
    assert len(text) < MAX_DESCRIPTION_CHARS + 600
    assert text.endswith("…")


def test_user_prompt_carries_both_sides_and_the_locale():
    prompt = build_user_prompt(_prefs(), _job(), locale="pt")
    assert "Junior AI engineer" in prompt
    assert "Build LLM pipelines" in prompt
    assert "pt" in prompt


def test_system_prompt_demands_evidence_and_conservatism():
    lowered = SYSTEM_PROMPT.lower()
    assert "only" in lowered and "score" in lowered


def _long_job() -> Job:
    return Job(
        source="t",
        external_id="a",
        title="AI Engineer",
        company="Acme",
        location="Berlin",
        remote=True,
        url="https://x/a",
        description="Python and LLM work. " + ("boilerplate about our culture. " * 400),
        content_hash="h",
        tags=["Machine Learning", "Python"],
    )


def test_embedding_text_keeps_title_and_tags():
    text = job_embedding_text(_long_job())

    assert "AI Engineer" in text
    assert "Machine Learning, Python" in text


def test_embedding_text_truncates_the_description():
    """The vector should describe the role, not 4,000 characters of company boilerplate."""
    text = job_embedding_text(_long_job())

    assert len(text) < 1000
    assert text.endswith("…")


def test_embedding_text_is_far_shorter_than_the_prompt_text():
    """The split exists so the prefilter stops paying ~1,070 tokens a job."""
    job = _long_job()

    assert len(job_embedding_text(job)) < len(job_text(job)) / 4


def test_prompt_text_still_carries_the_full_description():
    """Only the prefilter gets the short form; the LLM must keep deciding on everything."""
    job = _long_job()

    text = job_text(job)

    assert len(text) > 5000
    assert "Company: Acme" in text


def test_a_short_description_is_not_truncated():
    job = _long_job()
    job.description = "Python and LLM work."

    assert job_embedding_text(job).endswith("Python and LLM work.")

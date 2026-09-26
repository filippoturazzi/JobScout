from jobscout.matching.prompts import (
    MAX_DESCRIPTION_CHARS,
    SYSTEM_PROMPT,
    build_user_prompt,
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

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from jobscout.api.schemas import PreferencesUpdate
from jobscout.matching.terms import ExtractedProfile, extract_profile, profile_hash
from jobscout.models import UserPreferences
from tests.matching.fakes import CountingChatModel

PARAGRAPH = "Junior AI engineer, remote, Brazil or Portugal, Python and LangChain, no seniors."


def fake(**fields: Any) -> Any:
    return CountingChatModel(results=[ExtractedProfile(**fields)])


def test_extraction_returns_ranked_terms_and_structured_fields():
    llm = fake(
        terms=["ai engineer", "python", "langchain"],
        titles=["AI Engineer"],
        seniority=["Junior"],
        work_modes=["remote"],
        regions=["Brazil", "Portugal"],
        required_skills=["Python"],
        excluded_keywords=["senior"],
    )
    result = extract_profile(PARAGRAPH, llm)
    assert result.terms == ["ai engineer", "python", "langchain"]
    assert result.titles == []  # never filled: see ExtractedProfile
    assert result.seniority == ["junior"]
    assert result.work_modes == ["remote"]
    assert result.regions == ["Brazil", "Portugal"]
    assert result.required_skills == ["Python"]
    assert result.excluded_keywords == ["senior"]
    assert llm.schemas == [ExtractedProfile]


def test_every_structured_field_exists_on_user_preferences():
    for name in ExtractedProfile.model_fields:
        if name != "terms":
            assert name in UserPreferences.model_fields


def test_terms_are_short():
    llm = fake(terms=["python", "I want to build agents with LLMs", "ai engineer", "a b c d"])
    result = extract_profile(PARAGRAPH, llm)
    assert result.terms == ["python", "ai engineer"]


def test_terms_are_deduplicated_keeping_the_first_position():
    result = extract_profile(PARAGRAPH, fake(terms=["Python", "ai", "python "]))
    assert result.terms == ["Python", "ai"]


def test_work_modes_are_normalised_to_what_the_filter_understands():
    llm = fake(terms=["python"], work_modes=["Remote", "on-site", "Hybrid", "anywhere", "remote"])
    assert extract_profile(PARAGRAPH, llm).work_modes == ["remote", "onsite", "hybrid"]


@pytest.mark.parametrize("paragraph", ["", "   \n\t "])
def test_an_empty_or_blank_paragraph_raises_without_calling_the_llm(paragraph):
    llm = fake(terms=["python"])
    with pytest.raises(ValueError, match="empty"):
        extract_profile(paragraph, llm)
    assert llm.calls == 0
    assert llm.schemas == []


def test_a_paragraph_the_llm_returns_no_terms_for_raises():
    llm = fake(terms=[])
    with pytest.raises(ValueError, match="No usable search terms"):
        extract_profile(PARAGRAPH, llm)
    assert llm.calls == 1


def test_a_paragraph_whose_terms_are_all_unusable_raises():
    llm = fake(terms=["   ", "this is far too long to be a term"])
    with pytest.raises(ValueError, match="No usable search terms"):
        extract_profile(PARAGRAPH, llm)


def test_the_hash_is_stable_across_whitespace_only_changes():
    assert profile_hash("junior  ai\nengineer ") == profile_hash(" junior ai engineer")


def test_the_hash_changes_when_the_words_change():
    assert profile_hash("junior ai engineer") != profile_hash("senior ai engineer")


def test_preferences_default_to_no_terms_and_no_hash():
    prefs = UserPreferences(user_id=1)
    assert prefs.search_terms == []
    assert prefs.profile_hash is None


def test_terms_are_capped_keeping_the_most_important():
    llm = fake(terms=[f"term{i}" for i in range(20)])
    result = extract_profile(PARAGRAPH, llm)
    assert result.terms == [f"term{i}" for i in range(8)]


def test_a_related_title_still_passes_after_the_extracted_profile_is_saved(session):
    from jobscout.models import Job
    from jobscout.pipeline.filters import job_matches_preferences
    from jobscout.pipeline.users import get_or_create_default_user, update_preferences

    llm = fake(
        terms=["ai engineer"],
        titles=["AI Engineer"],  # even if the LLM volunteers titles, they must not be kept
        work_modes=["remote"],
    )
    extracted = extract_profile(PARAGRAPH, llm)
    user = get_or_create_default_user(session)
    prefs, _ = update_preferences(
        session,
        user.id,
        {**extracted.model_dump(exclude={"terms"}), "search_terms": extracted.terms},
    )
    job = Job(
        source="s",
        external_id="1",
        title="Machine Learning Engineer",
        company="c",
        remote=True,
        url="u",
        description="d",
        content_hash="h",
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    assert prefs.titles == []
    assert job_matches_preferences(job, prefs)


def test_search_terms_cannot_be_sent_through_the_preferences_api_model():
    with pytest.raises(ValidationError):
        PreferencesUpdate(search_terms=None)
    with pytest.raises(ValidationError):
        PreferencesUpdate(search_terms=["python"])

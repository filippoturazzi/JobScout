from typing import Any

import pytest
from pydantic import ValidationError

from jobscout.api.schemas import PreferencesUpdate
from jobscout.matching.terms import ExtractedProfile, _LLMOutput, extract_profile, profile_hash
from jobscout.models import UserPreferences
from jobscout.pipeline.filters import job_matches_preferences
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
    assert result.work_modes == []
    assert result.regions == []
    assert result.required_skills == ["Python"]
    assert result.excluded_keywords == ["senior"]
    assert llm.schemas == [_LLMOutput]
    assert set(_LLMOutput.model_fields) == {
        "terms",
        "seniority",
        "required_skills",
        "excluded_keywords",
    }


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


def _saved_prefs(session, **llm_fields):
    from jobscout.pipeline.users import get_or_create_default_user, update_preferences

    extracted = extract_profile(PARAGRAPH, fake(terms=["ai engineer"], **llm_fields))
    user = get_or_create_default_user(session)
    prefs, _ = update_preferences(
        session,
        user.id,
        {**extracted.model_dump(exclude={"terms"}), "search_terms": extracted.terms},
    )
    return prefs


def _job(title="Machine Learning Engineer", location="Berlin, Germany", remote=True):
    from jobscout.models import Job

    return Job(
        source="s",
        external_id="1",
        title=title,
        company="c",
        location=location,
        remote=remote,
        url="u",
        description="d",
        content_hash="h",
    )


def test_a_related_title_still_passes_after_the_extracted_profile_is_saved(session):
    prefs = _saved_prefs(session, titles=["AI Engineer"])
    assert prefs.titles == []
    assert job_matches_preferences(_job(), prefs)


def test_a_brazilian_city_still_passes_after_a_brazil_preference_is_saved(session):
    prefs = _saved_prefs(session, regions=["Brazil"])
    assert prefs.regions == []
    assert job_matches_preferences(_job(location="Sao Paulo, SP", remote=False), prefs)


def test_an_onsite_job_still_passes_after_a_remote_preference_is_saved(session):
    prefs = _saved_prefs(session, work_modes=["remote"])
    assert prefs.work_modes == []
    assert job_matches_preferences(_job(remote=False), prefs)


def test_search_terms_cannot_be_sent_through_the_preferences_api_model():
    with pytest.raises(ValidationError):
        PreferencesUpdate(search_terms=None)
    with pytest.raises(ValidationError):
        PreferencesUpdate(search_terms=["python"])

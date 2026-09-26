from jobscout.models import Job, UserPreferences
from jobscout.pipeline.filters import filter_jobs, job_matches_preferences, tokenize


def job(title="AI Engineer", location="Berlin, Germany", remote=False, tags=None) -> Job:
    return Job(
        source="t",
        external_id=title.lower(),
        title=title,
        company="Acme",
        location=location,
        remote=remote,
        url="https://x",
        description="",
        tags=tags or [],
        content_hash="h",
    )


def prefs(**kw) -> UserPreferences:
    return UserPreferences(user_id=1, **kw)


def test_empty_preferences_accept_everything():
    assert job_matches_preferences(job(), prefs())
    assert job_matches_preferences(job(remote=True, location=None), prefs())


def test_excluded_keywords_reject_by_title_or_tag():
    p = prefs(excluded_keywords=["senior", "PHP"])
    assert not job_matches_preferences(job(title="Senior AI Engineer"), p)
    assert not job_matches_preferences(job(tags=["php"]), p)
    assert job_matches_preferences(job(title="AI Engineer"), p)


def test_work_modes():
    assert job_matches_preferences(job(remote=True), prefs(work_modes=["remote"]))
    assert not job_matches_preferences(job(remote=False), prefs(work_modes=["remote"]))
    assert job_matches_preferences(job(remote=False), prefs(work_modes=["hybrid"]))
    assert job_matches_preferences(job(remote=False), prefs(work_modes=["onsite"]))
    assert not job_matches_preferences(job(remote=True), prefs(work_modes=["onsite"]))
    assert job_matches_preferences(job(remote=True), prefs(work_modes=["remote", "onsite"]))


def test_regions_apply_to_onsite_only():
    p = prefs(regions=["Germany", "Portugal"])
    assert job_matches_preferences(job(location="Berlin, Germany"), p)
    assert job_matches_preferences(job(location="lisbon, portugal"), p)
    assert not job_matches_preferences(job(location="Paris, France"), p)
    assert not job_matches_preferences(job(location=None), p)
    assert job_matches_preferences(job(location="Paris, France", remote=True), p)


def test_titles_match_by_word_subset():
    p = prefs(titles=["AI Engineer", "Machine Learning Engineer"])
    assert job_matches_preferences(job(title="AI Application Engineer (m/f/d)"), p)
    assert job_matches_preferences(job(title="Machine Learning Engineer"), p)
    assert not job_matches_preferences(job(title="Data Analyst"), p)
    assert not job_matches_preferences(job(title="AI Researcher"), p)


def test_filter_jobs_preserves_order():
    jobs = [job(title="Data Analyst"), job(title="AI Engineer"), job(title="AI Lead Engineer")]
    out = filter_jobs(jobs, prefs(titles=["AI Engineer"]))
    assert [j.title for j in out] == ["AI Engineer", "AI Lead Engineer"]


def test_titles_ignore_trailing_punctuation_and_keep_dotted_tech():
    p = prefs(titles=["AI Engineer", ".NET Developer", "C++ Developer"])
    assert job_matches_preferences(job(title="Senior AI Engineer."), p)
    assert job_matches_preferences(job(title=".NET Developer (m/f/d)"), p)
    assert job_matches_preferences(job(title="C++ Developer"), p)
    assert not job_matches_preferences(job(title="Net Developer"), p)


def test_tokenize_preserves_order_and_handles_tech_tokens():
    assert tokenize("Senior .NET / C++ Engineer.") == ["senior", ".net", "c++", "engineer"]
    assert tokenize("") == []
    assert tokenize("Zürich, São Paulo") == ["zürich", "são", "paulo"]


def test_exclusions_match_whole_tokens_not_substrings():
    p = prefs(excluded_keywords=["ai"])
    assert job_matches_preferences(job(title="Maintenance Engineer"), p)
    assert not job_matches_preferences(job(title="AI Engineer"), p)
    assert not job_matches_preferences(job(title="Engineer", tags=["AI"]), p)


def test_exclusions_match_contiguous_phrases():
    p = prefs(excluded_keywords=["machine learning"])
    assert not job_matches_preferences(job(title="Machine Learning Engineer"), p)
    assert job_matches_preferences(job(title="Learning Platform Machine Operator"), p)
    assert not job_matches_preferences(job(title="Engineer", tags=["Machine Learning"]), p)


def test_unicode_keywords_do_not_fragment():
    p = prefs(excluded_keywords=["Öl"])
    assert job_matches_preferences(job(title="L & D Manager"), p)
    assert not job_matches_preferences(job(title="Öl und Gas Engineer"), p)


def test_regions_match_location_segments_not_substrings():
    p = prefs(regions=["US"])
    assert not job_matches_preferences(job(location="Sydney, Australia"), p)
    assert job_matches_preferences(job(location="Austin, TX, US"), p)

    p = prefs(regions=["Germany", "New York"])
    assert job_matches_preferences(job(location="Berlin, Berlin, Germany"), p)
    assert job_matches_preferences(job(location="New York City, NY"), p)
    assert not job_matches_preferences(job(location="Paris, France"), p)

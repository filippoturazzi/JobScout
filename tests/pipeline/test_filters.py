import pandas as pd
import pytest

from jobscout.config import Settings
from jobscout.models import Job, UserPreferences
from jobscout.pipeline.filters import filter_jobs, job_matches_preferences, tokenize
from jobscout.sources import jobspy_base
from jobscout.sources.base import SearchQuery
from jobscout.sources.linkedin import LinkedInSource
from tests.conftest import load_jsonl


def job(
    title="AI Engineer", location="Berlin, Germany", remote=False, tags=None, description=""
) -> Job:
    return Job(
        source="t",
        external_id=title.lower(),
        title=title,
        company="Acme",
        location=location,
        remote=remote,
        url="https://x",
        description=description,
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


def test_regions_decide_on_site_jobs_by_location():
    p = prefs(regions=["Germany", "Portugal"])
    assert job_matches_preferences(job(location="Berlin, Germany"), p)
    assert job_matches_preferences(job(location="lisbon, portugal"), p)
    assert not job_matches_preferences(job(location="Paris, France"), p)
    assert not job_matches_preferences(job(location=None), p)


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


def test_a_country_matches_its_names_and_codes_with_accents_folded():
    for region in ["Brasil", "Brazil", "br", "BRASIL"]:
        p = prefs(regions=[region])
        assert job_matches_preferences(job(location="São Paulo, Brazil"), p)
        assert job_matches_preferences(job(location="Curitiba, Paraná, Brasil"), p)
        assert job_matches_preferences(job(location="Recife, PE, BR"), p)
    assert job_matches_preferences(job(location="Málaga, España"), prefs(regions=["Spain"]))
    assert job_matches_preferences(job(location="Sao Paulo"), prefs(regions=["São Paulo"]))


def test_a_country_code_matches_only_as_the_last_part_of_a_location():
    # "de" is Germany's code and a word in half of Brazil's place names.
    assert not job_matches_preferences(job(location="Rio de Janeiro"), prefs(regions=["Germany"]))
    assert job_matches_preferences(job(location="Munich, DE"), prefs(regions=["Germany"]))


def _linkedin_jobs(
    monkeypatch, searched: list[str], capture: str = "linkedin_sample.jsonl"
) -> list[Job]:
    """Rows built the way production builds them: a real capture, through the source."""
    rows = load_jsonl(capture)

    def fake(**kwargs):
        frame = pd.DataFrame(rows)
        frame.attrs = {"errors": {}, "warnings": {}}
        return frame

    monkeypatch.setattr(jobspy_base, "scrape_jobs", fake)
    source = LinkedInSource(Settings(_env_file=None))
    raw_jobs = source.fetch(SearchQuery(keywords=["python"], locations=searched))
    return [Job(**raw.model_dump(), content_hash="h") for raw in raw_jobs]


@pytest.mark.parametrize("region", ["Brasil", "Brazil", "br"])
def test_every_captured_linkedin_posting_passes_a_brazilian_region(monkeypatch, region):
    # "Greater São Paulo Area" and "Greater Curitiba" name no country at all. They pass
    # because LinkedIn was searched in that region, which the source records on the row.
    jobs = _linkedin_jobs(monkeypatch, searched=["Brasil"])
    assert len(jobs) == 5
    assert len(filter_jobs(jobs, prefs(regions=[region]))) == 5


def test_a_search_in_an_older_region_does_not_vouch_for_a_new_one(monkeypatch):
    jobs = _linkedin_jobs(monkeypatch, searched=["Brasil"])
    kept = filter_jobs(jobs, prefs(regions=["Portugal"]))
    assert [j.remote for j in kept] == [True]  # only the remote posting survives


def test_without_a_searched_region_the_location_alone_decides(monkeypatch):
    jobs = _linkedin_jobs(monkeypatch, searched=[])
    kept = filter_jobs(jobs, prefs(regions=["Brasil"]))
    assert sorted(j.location or "" for j in kept) == [
        "Curitiba, Paraná, Brazil",
        "Greater Rio de Janeiro",  # remote
        "São Paulo, Brazil",
    ]


def test_a_search_record_never_overrules_a_location_naming_another_country(monkeypatch):
    # A real capture: LinkedIn searched for "Brasil" and answered with five US postings. If
    # a site ignores the location again, its record must not pass them off as Brazilian.
    jobs = _linkedin_jobs(monkeypatch, ["Brasil"], capture="linkedin_location_brasil.jsonl")
    assert {j.location.rsplit(", ", 1)[-1] for j in jobs if j.location} == {"USA"}
    assert filter_jobs(jobs, prefs(regions=["Brasil"])) == []


# ---- a remote job is open to the places it names


@pytest.mark.parametrize(
    "location",
    [
        "United States",  # the most common value on the boards
        "India",
        "Canada, United Kingdom, United States",
        "Europe, USA, Canada, APAC",
        "Europe",
    ],
)
def test_a_remote_job_limited_to_elsewhere_fails_the_region(location):
    remote = job(location=location, remote=True)
    assert not job_matches_preferences(remote, prefs(regions=["Brasil"]))


@pytest.mark.parametrize(
    "location",
    [
        None,  # Himalayas sends no restriction at all
        "Worldwide",
        "Remoto, Brazil",
        "Argentina, Brazil, Chile, Uruguay",
        "Latin America",
        "LATAM",
        "Greater Rio de Janeiro",  # names no country, so nothing says it is closed to Brazil
    ],
)
def test_a_remote_job_that_may_be_open_to_the_region_passes(location):
    assert job_matches_preferences(job(location=location, remote=True), prefs(regions=["Brasil"]))


def test_an_area_counts_for_the_countries_inside_it():
    remote_in_europe = job(location="Europe", remote=True)
    assert job_matches_preferences(remote_in_europe, prefs(regions=["Portugal"]))
    assert not job_matches_preferences(remote_in_europe, prefs(regions=["Canada"]))


def test_a_city_alone_cannot_judge_where_a_remote_job_is_open():
    # No table says which country "Recife" is in, and hiding a job takes evidence.
    remote = job(location="United States", remote=True)
    assert job_matches_preferences(remote, prefs(regions=["Recife"]))


def test_a_search_record_does_not_vouch_for_a_country_outside_the_old_table(monkeypatch):
    # France was unknown to the table, so "Paris, France" passed as "names no country".
    rows = load_jsonl("linkedin_sample.jsonl")
    rows[0]["location"] = "Paris, France"
    rows[0]["is_remote"] = False

    def fake(**kwargs):
        frame = pd.DataFrame(rows[:1])
        frame.attrs = {"errors": {}, "warnings": {}}
        return frame

    monkeypatch.setattr(jobspy_base, "scrape_jobs", fake)
    [raw] = LinkedInSource(Settings(_env_file=None)).fetch(
        SearchQuery(keywords=["python"], locations=["Brasil"])
    )
    posting = Job(**raw.model_dump(), content_hash="h")
    assert not job_matches_preferences(posting, prefs(regions=["Brasil"]))


# ---- hybrid and on-site are told apart when the posting says which it is


@pytest.mark.parametrize(
    "posting",
    [
        {"title": "AI Engineer (Hybrid)"},
        {"title": "Engenheiro de IA - Híbrido"},
        {"location": "Hybrid - São Paulo, Brazil"},
        {"description": "Modelo de trabalho: híbrido, 3 dias no escritório."},
        {"description": "This is a hybrid role based in Lisbon."},
    ],
)
def test_a_hybrid_posting_answers_only_to_hybrid(posting):
    hybrid = job(**posting)
    assert job_matches_preferences(hybrid, prefs(work_modes=["hybrid"]))
    assert not job_matches_preferences(hybrid, prefs(work_modes=["onsite"]))


@pytest.mark.parametrize(
    "posting",
    [
        {"title": "Desenvolvedor Python - Presencial"},
        {"title": "AI Engineer (On-site)"},
        {"description": "Regime de trabalho: 100% presencial em Curitiba."},
        {"description": "This is a fully on-site position."},
    ],
)
def test_an_on_site_posting_answers_only_to_on_site(posting):
    on_site = job(**posting)
    assert job_matches_preferences(on_site, prefs(work_modes=["onsite"]))
    assert not job_matches_preferences(on_site, prefs(work_modes=["hybrid"]))


@pytest.mark.parametrize(
    "description",
    [
        "",
        "Experience with hybrid cloud and hybrid mobile apps.",
        "Reuniões presenciais com clientes e on-site interviews.",
    ],
)
def test_a_posting_that_does_not_say_stays_a_candidate_for_both(description):
    unknown = job(description=description)
    assert job_matches_preferences(unknown, prefs(work_modes=["hybrid"]))
    assert job_matches_preferences(unknown, prefs(work_modes=["onsite"]))


def test_a_hybrid_posting_passes_when_both_modes_are_accepted():
    hybrid = job(title="AI Engineer (Hybrid)")
    assert job_matches_preferences(hybrid, prefs(work_modes=["hybrid", "onsite"]))


# ---- "abroad": anywhere except the countries the user rules out


@pytest.mark.parametrize(
    ("location", "remote"),
    [("São Paulo, Brazil", False), ("Brazil", True), ("Recife, PE, BR", False)],
)
def test_an_excluded_country_removes_its_jobs(location, remote):
    p = prefs(excluded_regions=["Brasil"])
    assert not job_matches_preferences(job(location=location, remote=remote), p)


@pytest.mark.parametrize(
    "location",
    [None, "Worldwide", "Berlin, Germany", "Argentina, Brazil, Chile", "Latin America"],
)
def test_an_excluded_country_leaves_jobs_open_elsewhere(location):
    assert job_matches_preferences(job(location=location), prefs(excluded_regions=["Brasil"]))


def test_a_search_record_in_an_excluded_country_counts_as_its_location(monkeypatch):
    jobs = _linkedin_jobs(monkeypatch, searched=["Brasil"])
    greater_curitiba = next(j for j in jobs if j.location == "Greater Curitiba")
    assert not job_matches_preferences(greater_curitiba, prefs(excluded_regions=["Brasil"]))

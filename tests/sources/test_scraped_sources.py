"""The LinkedIn and Indeed sources: their site settings and Indeed's region mapping.

Google Jobs is deliberately absent: a live capture returned no postings, and fixtures are
never hand-written, so there is nothing to test it against.
"""

import pandas as pd
import pytest
from jobspy.model import ScraperInput

from jobscout.config import Settings
from jobscout.sources import jobspy_base
from jobscout.sources.base import SearchQuery
from jobscout.sources.indeed import IndeedSource, country_for
from jobscout.sources.linkedin import LinkedInSource
from jobscout.sources.registry import build_sources, source_statuses


def test_each_site_is_registered_and_needs_no_credential():
    settings = Settings(_env_file=None, sources="linkedin,indeed")
    assert [s.name for s in build_sources(settings)] == ["linkedin", "indeed"]
    assert all(s.active for s in source_statuses(settings))


def test_linkedin_asks_for_descriptions_and_indeed_does_not():
    settings = Settings(_env_file=None)
    assert LinkedInSource(settings).fetch_description is True
    assert IndeedSource(settings).fetch_description is False


def test_the_scraped_sources_use_the_jobspy_term_budget():
    settings = Settings(_env_file=None, jobspy_max_terms=2)
    assert LinkedInSource(settings).term_budget == 2
    assert IndeedSource(settings).term_budget == 2


@pytest.mark.parametrize(
    ("region", "country"),
    [
        ("Brasil", "brazil"),
        ("brazil", "brazil"),
        ("BR", "brazil"),
        ("Portugal", "portugal"),
        ("España", "spain"),
        ("spain", "spain"),
        ("USA", "usa"),
        ("United States", "usa"),
        ("UK", "uk"),
        ("United Kingdom", "uk"),
        ("Germany", "germany"),
        ("Deutschland", "germany"),
        ("Canadá", "canada"),
        ("  canada ", "canada"),
    ],
)
def test_indeed_maps_a_region_to_a_country(region, country):
    assert country_for([region]) == (country, None)


def test_the_first_recognised_region_wins():
    assert country_for(["Brazil", "Portugal"]) == ("brazil", None)
    assert country_for(["remoto", "Portugal"]) == ("portugal", None)


def test_an_unmapped_region_falls_back_to_worldwide_and_says_so():
    assert country_for(["remoto"]) == ("worldwide", "remoto")
    assert country_for([]) == ("worldwide", None)


def _capture_scrape(monkeypatch):
    calls: list[dict] = []

    def fake(**kwargs):
        calls.append(kwargs)
        frame = pd.DataFrame([])
        frame.attrs = {"errors": {}, "warnings": {}}
        return frame

    monkeypatch.setattr(jobspy_base, "scrape_jobs", fake)
    return calls


def test_indeed_searches_the_mapped_country(monkeypatch):
    calls = _capture_scrape(monkeypatch)
    source = IndeedSource(Settings(_env_file=None))
    source.fetch(SearchQuery(keywords=["python"], locations=["Brasil"]))
    assert calls[0]["search_term"] == "python"
    assert calls[0]["country_indeed"] == "brazil"
    assert source.warnings == []


def test_an_unrecognised_stored_region_is_searched_worldwide_and_named_in_a_warning(
    monkeypatch,
):
    calls = _capture_scrape(monkeypatch)
    source = IndeedSource(Settings(_env_file=None))
    source.fetch(SearchQuery(keywords=["python"], locations=["remoto"]))
    # JobSpy 1.4.1 rejects "worldwide" as a country, so the argument is left out and Indeed
    # uses its un-localised default instead of the whole run crashing.
    assert "country_indeed" not in calls[0]
    assert len(source.warnings) == 1
    assert "remoto" in source.warnings[0]


@pytest.mark.parametrize("regions", [["Brasil"], ["remoto"], []])
def test_the_indeed_arguments_are_accepted_by_the_installed_jobspy(regions):
    kwargs = IndeedSource(Settings(_env_file=None)).search_kwargs(
        SearchQuery(keywords=["python"], locations=regions)
    )
    ScraperInput.model_validate({"site_type": ["indeed"], **kwargs})


def test_the_region_warning_survives_every_term(monkeypatch):
    _capture_scrape(monkeypatch)
    source = IndeedSource(Settings(_env_file=None))
    query = SearchQuery(keywords=["python"], locations=["remoto"])
    source.fetch(query)
    source.fetch(query)
    assert len(source.warnings) == 1 and "remoto" in source.warnings[0]


def test_linkedin_passes_the_term_and_requests_descriptions(monkeypatch):
    calls = _capture_scrape(monkeypatch)
    LinkedInSource(Settings(_env_file=None)).fetch(SearchQuery(keywords=["python"]))
    assert calls[0]["site_name"] == ["linkedin"]
    assert calls[0]["search_term"] == "python"
    assert calls[0]["fetch_description"] is True

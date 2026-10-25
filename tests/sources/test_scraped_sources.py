"""The LinkedIn and Indeed sources: their site settings and Indeed's region mapping.

Google Jobs is deliberately absent: a live capture returned no postings, and fixtures are
never hand-written, so there is nothing to test it against.
"""

import pandas as pd
import pytest
from jobspy.model import ScraperInput
from pydantic import ConfigDict, ValidationError

from jobscout.config import Settings
from jobscout.sources import jobspy_base
from jobscout.sources.base import SearchQuery
from jobscout.sources.indeed import IndeedSource, country_for
from jobscout.sources.linkedin import LinkedInSource
from jobscout.sources.registry import build_sources, source_statuses
from tests.conftest import load_jsonl


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


def test_blank_regions_are_skipped():
    assert country_for(["", "Brasil"]) == ("brazil", None)
    assert country_for(["  ", "remoto"]) == (None, "remoto")
    assert country_for([""]) == (None, None)
    assert country_for(["  "]) == (None, None)


def test_ca_is_not_read_as_canada():
    # Two letters could as well mean California; spelling Canada out still works.
    assert country_for(["CA"]) == (None, "CA")


def test_an_unmapped_region_yields_no_country_and_names_the_value():
    assert country_for(["remoto"]) == (None, "remoto")
    assert country_for([]) == (None, None)


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


@pytest.mark.parametrize(
    ("regions", "named"),
    [(["remoto"], "remoto"), ([], "no region is set"), ([" "], "no region is set")],
)
def test_without_a_known_region_indeed_does_not_search_and_says_so(monkeypatch, regions, named):
    calls = _capture_scrape(monkeypatch)
    source = IndeedSource(Settings(_env_file=None))
    jobs = source.fetch(SearchQuery(keywords=["python"], locations=regions))
    assert calls == []
    assert jobs == []
    assert len(source.warnings) == 1
    assert named in source.warnings[0]
    # The composer drains warnings once after all terms, so a second term must keep it.
    source.fetch(SearchQuery(keywords=["java"], locations=regions))
    assert len(source.warnings) == 1


class _StrictScraperInput(ScraperInput):
    """JobSpy's own validator, but rejecting a keyword it does not know.

    ``ScraperInput`` ignores unknown keys, so a renamed argument would pass silently.
    """

    model_config = ConfigDict(extra="forbid")


@pytest.mark.parametrize("source_class", [LinkedInSource, IndeedSource])
def test_every_argument_sent_to_scrape_jobs_is_one_the_installed_jobspy_accepts(
    monkeypatch, source_class
):
    calls = _capture_scrape(monkeypatch)
    settings = Settings(_env_file=None, jobspy_proxies="user:pass@10.0.0.1:8080")
    source_class(settings).fetch(SearchQuery(keywords=["python"], locations=["Brasil"]))
    assert calls, "scrape_jobs was not called"
    _StrictScraperInput.model_validate(calls[0])


def test_the_strict_guard_rejects_an_unknown_keyword():
    with pytest.raises(ValidationError):
        _StrictScraperInput.model_validate({"site_name": ["indeed"], "search_trm": "python"})


def test_linkedin_passes_the_term_and_requests_descriptions(monkeypatch):
    calls = _capture_scrape(monkeypatch)
    LinkedInSource(Settings(_env_file=None)).fetch(SearchQuery(keywords=["python"]))
    assert calls[0]["site_name"] == ["linkedin"]
    assert calls[0]["search_term"] == "python"
    assert calls[0]["fetch_description"] is True


@pytest.mark.parametrize(
    ("regions", "location"),
    [
        (["Brazil"], "Brazil"),
        # LinkedIn does not read "Brasil": a live search for it returned five US postings
        # (``linkedin_location_brasil.jsonl``). A recognised country is sent in English.
        (["Brasil"], "Brazil"),
        (["BR"], "Brazil"),
        (["Estados Unidos"], "United States"),
        (["remoto", "Brasil"], "Brazil"),  # the first region that names a country wins
        (["São Paulo"], "São Paulo"),  # not a country: sent as typed
    ],
)
def test_linkedin_searches_the_stored_region(monkeypatch, regions, location):
    calls = _capture_scrape(monkeypatch)
    LinkedInSource(Settings(_env_file=None)).fetch(
        SearchQuery(keywords=["python"], locations=regions, remote_only=True)
    )
    assert calls[0]["location"] == location


def test_without_a_stored_region_no_location_is_sent(monkeypatch):
    calls = _capture_scrape(monkeypatch)
    LinkedInSource(Settings(_env_file=None)).fetch(SearchQuery(keywords=["python"]))
    assert "location" not in calls[0]


def test_linkedin_does_not_send_is_remote(monkeypatch):
    # The installed python-jobspy (1.4.1) ignores it for LinkedIn and warns; the warning
    # would be drained into every run's errors while nothing changed in the search.
    calls = _capture_scrape(monkeypatch)
    LinkedInSource(Settings(_env_file=None)).fetch(
        SearchQuery(keywords=["python"], remote_only=True)
    )
    assert "is_remote" not in calls[0]


def test_indeed_filters_remote_when_that_is_the_stored_work_mode(monkeypatch):
    calls = _capture_scrape(monkeypatch)
    IndeedSource(Settings(_env_file=None)).fetch(
        SearchQuery(keywords=["python"], locations=["Brasil"], remote_only=True)
    )
    assert calls[0]["is_remote"] is True
    # country_indeed already picks the market; a location would narrow it to a 50-mile radius.
    assert "location" not in calls[0]


def _scrape_returning(monkeypatch, rows):
    def fake(**kwargs):
        frame = pd.DataFrame(rows)
        frame.attrs = {"errors": {}, "warnings": {}}
        return frame

    monkeypatch.setattr(jobspy_base, "scrape_jobs", fake)


def test_each_posting_records_the_region_it_was_searched_in(monkeypatch):
    _scrape_returning(monkeypatch, load_jsonl("linkedin_sample.jsonl"))
    linkedin = LinkedInSource(Settings(_env_file=None))
    jobs = linkedin.fetch(SearchQuery(keywords=["python"], locations=[" ", "Brasil"]))
    assert {job.raw["searched_region"] for job in jobs} == {"Brasil"}

    _scrape_returning(monkeypatch, load_jsonl("indeed_sample.jsonl"))
    indeed = IndeedSource(Settings(_env_file=None))
    # Indeed searches the first region it recognises, so that is the one it vouches for.
    jobs = indeed.fetch(SearchQuery(keywords=["python"], locations=["remoto", "Brazil"]))
    assert {job.raw["searched_region"] for job in jobs} == {"Brazil"}


@pytest.mark.parametrize("regions", [[], ["São Paulo"]])
def test_only_a_search_in_a_known_country_is_recorded(monkeypatch, regions):
    # A location the site may not understand vouches for nothing: LinkedIn answers one it
    # cannot read with postings from elsewhere.
    _scrape_returning(monkeypatch, load_jsonl("linkedin_sample.jsonl"))
    source = LinkedInSource(Settings(_env_file=None))
    jobs = source.fetch(SearchQuery(keywords=["python"], locations=regions))
    assert jobs
    assert all("searched_region" not in job.raw for job in jobs)

import httpx
import pytest
import respx

from jobscout.sources.base import SearchQuery
from jobscout.sources.himalayas import BASE_URL, HimalayasSource
from tests.conftest import load_fixture


@pytest.fixture
def sample():
    return load_fixture("himalayas_search.json")


def _mock(sample):
    return respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=sample))


@respx.mock
def test_fetch_maps_fields(sample):
    _mock(sample)
    jobs = HimalayasSource().fetch(SearchQuery(keywords=["machine learning engineer"]))

    assert len(jobs) == 3
    first = jobs[0]
    assert first.source == "himalayas"
    assert first.external_id == sample["jobs"][0]["guid"]
    assert first.title == "Machine Learning Engineer"
    assert first.company == sample["jobs"][0]["companyName"]
    assert first.url == first.external_id
    assert first.remote is True
    assert first.tags == sample["jobs"][0]["seniority"]
    assert (first.salary_min, first.salary_max) == (100000, 130000)
    assert first.salary_currency == "CAD"
    assert first.posted_at is not None
    assert first.description and "<" not in first.description


@respx.mock
def test_job_without_salary_has_none(sample):
    _mock(sample)
    jobs = HimalayasSource().fetch(SearchQuery(keywords=["ml"]))
    assert jobs[1].salary_min is None and jobs[1].salary_max is None


@respx.mock
def test_hourly_salary_is_not_reported_as_annual(sample):
    sample["jobs"][0]["salaryPeriod"] = "hourly"
    _mock(sample)
    jobs = HimalayasSource().fetch(SearchQuery(keywords=["ml"]))
    assert jobs[0].salary_min is None and jobs[0].salary_currency is None


@respx.mock
def test_empty_excerpt_still_yields_a_job(sample):
    _mock(sample)
    jobs = HimalayasSource().fetch(SearchQuery(keywords=["ml"]))
    assert sample["jobs"][2]["excerpt"] == ""
    assert jobs[2].description


@respx.mock
def test_description_falls_back_to_excerpt(sample):
    sample["jobs"][0]["description"] = ""
    _mock(sample)
    jobs = HimalayasSource().fetch(SearchQuery(keywords=["ml"]))
    assert jobs[0].description == sample["jobs"][0]["excerpt"]


@respx.mock
def test_fetch_sends_q_not_query(sample):
    route = _mock(sample)
    HimalayasSource().fetch(SearchQuery(keywords=["kubernetes"]))
    params = route.calls[0].request.url.params
    assert params["q"] == "kubernetes"
    assert "query" not in params and "search" not in params
    assert params["page"] == "1"


@respx.mock
def test_remote_restrictions_become_location(sample):
    sample["jobs"][0]["locationRestrictions"] = ["Brazil", "Canada"]
    _mock(sample)
    jobs = HimalayasSource().fetch(SearchQuery(keywords=["ml"]))
    assert jobs[0].location == "Brazil, Canada"
    assert jobs[2].location is None  # the fixture job has no restrictions
    assert jobs[2].remote is True


@respx.mock
def test_a_job_missing_a_required_field_is_skipped_and_the_rest_survive(sample):
    assert sample["jobs"][3]["guid"] is None
    _mock(sample)
    jobs = HimalayasSource().fetch(SearchQuery(keywords=["ml"]))
    assert len(jobs) == 3
    assert all(j.external_id for j in jobs)


@respx.mock
def test_one_request_per_term(sample):
    route = _mock(sample)
    jobs = HimalayasSource().fetch(SearchQuery(keywords=["a", "b"]))
    assert route.call_count == 2
    assert [c.request.url.params["q"] for c in route.calls] == ["a", "b"]
    assert len(jobs) == 3  # the same postings across terms are deduplicated


@respx.mock
def test_pages_are_followed_up_to_max_and_stop_when_empty(sample):
    route = respx.get(BASE_URL).mock(
        side_effect=[httpx.Response(200, json=sample), httpx.Response(200, json={"jobs": []})]
    )
    HimalayasSource(max_pages=3).fetch(SearchQuery(keywords=["ml"]))
    assert route.call_count == 2


@respx.mock
def test_no_keywords_fetches_nothing(sample):
    route = _mock(sample)
    assert HimalayasSource().fetch(SearchQuery()) == []
    assert route.call_count == 0

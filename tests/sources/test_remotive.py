import httpx
import pytest
import respx

from jobscout.sources.base import SearchQuery
from jobscout.sources.remotive import BASE_URL, RemotiveSource
from tests.conftest import load_fixture


@pytest.fixture
def sample():
    return load_fixture("remotive_search.json")


def _mock(sample):
    return respx.get(BASE_URL).mock(return_value=httpx.Response(200, json=sample))


@respx.mock
def test_fetch_maps_fields(sample):
    _mock(sample)
    jobs = RemotiveSource().fetch(SearchQuery(keywords=["machine learning"]))

    assert len(jobs) == 3
    first = jobs[0]
    raw = sample["jobs"][0]
    assert first.source == "remotive"
    assert first.external_id == str(raw["id"])
    assert first.title == "Software Engineer, AI Coding Tasks"
    assert first.company == raw["company_name"]
    assert first.url == raw["url"]
    assert first.remote is True
    assert first.location == "Worldwide"
    assert first.posted_at is not None and first.posted_at.year == 2026
    assert "AI/ML" in first.tags
    assert all(tag == tag.strip() for tag in first.tags)  # "Typescript " is padded upstream


@respx.mock
def test_salary_text_is_not_parsed_into_numbers(sample):
    _mock(sample)
    jobs = RemotiveSource().fetch(SearchQuery(keywords=["ml"]))
    assert sample["jobs"][0]["salary"] == "$1000 per task"
    assert jobs[0].salary_min is None and jobs[0].salary_max is None
    assert jobs[0].raw["salary"] == "$1000 per task"


@respx.mock
def test_job_with_empty_salary_still_yields_a_job(sample):
    _mock(sample)
    jobs = RemotiveSource().fetch(SearchQuery(keywords=["ml"]))
    assert sample["jobs"][1]["salary"] == ""
    assert jobs[1].salary_min is None and jobs[1].salary_currency is None


@respx.mock
def test_html_description_is_rendered_to_text(sample):
    _mock(sample)
    jobs = RemotiveSource().fetch(SearchQuery(keywords=["ml"]))
    assert "<p>" in sample["jobs"][1]["description"]
    assert jobs[1].description and "<" not in jobs[1].description


@respx.mock
def test_empty_description_still_yields_a_job(sample):
    sample["jobs"][0]["description"] = ""
    _mock(sample)
    jobs = RemotiveSource().fetch(SearchQuery(keywords=["ml"]))
    assert jobs[0].description == ""


@respx.mock
def test_empty_location_becomes_none(sample):
    sample["jobs"][0]["candidate_required_location"] = ""
    _mock(sample)
    jobs = RemotiveSource().fetch(SearchQuery(keywords=["ml"]))
    assert jobs[0].location is None
    assert jobs[0].remote is True


@respx.mock
def test_fetch_sends_search_not_q(sample):
    route = _mock(sample)
    RemotiveSource().fetch(SearchQuery(keywords=["kubernetes"]))
    params = route.calls[0].request.url.params
    assert params["search"] == "kubernetes"
    assert "q" not in params and "query" not in params


@respx.mock
def test_a_job_with_a_null_id_is_skipped_and_the_rest_survive(sample):
    # The fourth fixture job is the third with ``id`` set to null (hand-edited).
    assert sample["jobs"][3]["id"] is None
    _mock(sample)
    jobs = RemotiveSource().fetch(SearchQuery(keywords=["ml"]))
    assert len(jobs) == 3
    assert "None" not in {j.external_id for j in jobs}


@respx.mock
def test_a_job_with_a_null_title_is_skipped_by_validation(sample):
    sample["jobs"][0]["title"] = None
    _mock(sample)
    jobs = RemotiveSource().fetch(SearchQuery(keywords=["ml"]))
    assert len(jobs) == 2


@respx.mock
def test_one_request_per_term(sample):
    route = _mock(sample)
    jobs = RemotiveSource().fetch(SearchQuery(keywords=["a", "b"]))
    assert route.call_count == 2
    assert [c.request.url.params["search"] for c in route.calls] == ["a", "b"]
    assert len(jobs) == 3  # the same postings across terms are deduplicated


@respx.mock
def test_no_keywords_fetches_nothing(sample):
    route = _mock(sample)
    assert RemotiveSource().fetch(SearchQuery()) == []
    assert route.call_count == 0

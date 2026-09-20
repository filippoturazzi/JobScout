import copy
from datetime import datetime

import httpx
import pytest
import respx

from jobscout.sources.arbeitnow import BASE_URL, ArbeitnowSource
from jobscout.sources.base import RawJob, SearchQuery
from tests.conftest import load_fixture


@pytest.fixture
def sample():
    return load_fixture("arbeitnow_sample.json")


@respx.mock
def test_fetch_maps_fields(sample):
    respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(200, json=sample))
    jobs = ArbeitnowSource(max_pages=1).fetch(SearchQuery())

    assert len(jobs) == 3
    assert all(isinstance(j, RawJob) for j in jobs)
    first = jobs[0]
    assert first.source == "arbeitnow"
    assert first.external_id == "remote-ai-developer-nurnberg-177325"
    assert first.title == "AI Developer (m/f/d)"
    assert first.company == "Partspace"
    assert first.location == "Nürnberg"
    assert first.remote is True
    assert first.url.endswith("/remote-ai-developer-nurnberg-177325")
    assert first.description == (
        "Join the AI of Manufacturing PartSpace builds Document AI for CAD/CAM."
    )
    assert "LLMs" in first.tags
    assert first.posted_at == datetime(2026, 9, 19, 20, 9, 15)
    assert first.raw["slug"] == first.external_id


@respx.mock
def test_fetch_decodes_escaped_html(sample):
    respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(200, json=sample))
    jobs = ArbeitnowSource(max_pages=1).fetch(SearchQuery())
    assert jobs[1].description == "Brief info about Vinted Our marketplace."


@respx.mock
def test_fetch_follows_pages_up_to_max(sample):
    page1 = copy.deepcopy(sample)
    page1["links"]["next"] = f"{BASE_URL}?page=2"
    page2 = copy.deepcopy(sample)
    page2["data"] = [dict(sample["data"][0], slug="another-slug-1")]
    page2["links"]["next"] = f"{BASE_URL}?page=3"
    r1 = respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(200, json=page1))
    r2 = respx.get(BASE_URL, params={"page": 2}).mock(return_value=httpx.Response(200, json=page2))
    r3 = respx.get(BASE_URL, params={"page": 3}).mock(return_value=httpx.Response(200, json=sample))

    jobs = ArbeitnowSource(max_pages=2).fetch(SearchQuery())

    assert r1.called and r2.called and not r3.called
    assert [j.external_id for j in jobs][-1] == "another-slug-1"
    assert len(jobs) == 4


@respx.mock
def test_fetch_stops_when_no_next_link(sample):
    r1 = respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(200, json=sample))
    r2 = respx.get(BASE_URL, params={"page": 2}).mock(return_value=httpx.Response(200, json=sample))
    ArbeitnowSource(max_pages=5).fetch(SearchQuery())
    assert r1.called and not r2.called


@respx.mock
def test_remote_only_filters_client_side(sample):
    respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(200, json=sample))
    jobs = ArbeitnowSource(max_pages=1).fetch(SearchQuery(remote_only=True))
    assert [j.external_id for j in jobs] == ["remote-ai-developer-nurnberg-177325"]


@respx.mock
def test_http_error_raises(sample):
    respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        ArbeitnowSource(max_pages=1).fetch(SearchQuery())


@respx.mock
def test_sends_user_agent(sample):
    route = respx.get(BASE_URL, params={"page": 1}).mock(
        return_value=httpx.Response(200, json=sample)
    )
    ArbeitnowSource(max_pages=1).fetch(SearchQuery())
    assert "jobscout" in route.calls.last.request.headers["user-agent"].lower()


@respx.mock
def test_malformed_item_is_skipped_not_fatal(sample, caplog):
    broken = copy.deepcopy(sample)
    broken["data"].insert(1, {"company_name": "NoSlug GmbH", "title": "Broken"})
    respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(200, json=broken))
    with caplog.at_level("WARNING"):
        jobs = ArbeitnowSource(max_pages=1).fetch(SearchQuery())
    assert [j.external_id for j in jobs] == [j["slug"] for j in sample["data"]]
    assert "skipping malformed item" in caplog.text


@respx.mock
def test_injected_client_is_used_and_not_closed(sample):
    respx.get(BASE_URL, params={"page": 1}).mock(return_value=httpx.Response(200, json=sample))
    client = httpx.Client(headers={"User-Agent": "custom-agent"})
    try:
        jobs = ArbeitnowSource(client=client, max_pages=1).fetch(SearchQuery())
        assert len(jobs) == 3
        assert client.is_closed is False
    finally:
        client.close()

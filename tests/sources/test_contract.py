"""Generic contract every registered source must satisfy.

Each source registers a fixture file ``tests/fixtures/<name>_sample.json`` and the URL
it hits; the test mocks that URL and checks the RawJob invariants. Adding a source means
adding one entry to ``SOURCE_HTTP_FIXTURES`` here.
"""

import httpx
import pytest
import respx

from jobscout.config import Settings
from jobscout.sources.arbeitnow import BASE_URL as ARBEITNOW_URL
from jobscout.sources.base import JobSource, RawJob, SearchQuery
from jobscout.sources.registry import SOURCE_FACTORIES
from tests.conftest import load_fixture

SOURCE_HTTP_FIXTURES: dict[str, tuple[str, str]] = {
    "arbeitnow": (ARBEITNOW_URL, "arbeitnow_sample.json"),
}


@pytest.mark.parametrize("name", sorted(SOURCE_FACTORIES))
@respx.mock
def test_source_contract(name):
    assert name in SOURCE_HTTP_FIXTURES, f"register a fixture for source {name!r}"
    url, fixture = SOURCE_HTTP_FIXTURES[name]
    respx.get(url__startswith=url).mock(
        return_value=httpx.Response(200, json=load_fixture(fixture))
    )
    source = SOURCE_FACTORIES[name](Settings(_env_file=None))

    assert isinstance(source, JobSource)
    jobs = source.fetch(SearchQuery())

    assert jobs, "fixture must yield at least one job"
    ids = [j.external_id for j in jobs]
    assert len(ids) == len(set(ids)), "external_id must be unique within a fetch"
    for job in jobs:
        assert isinstance(job, RawJob)
        assert job.source == name
        assert job.external_id and job.title and job.url and job.description
        assert "<" not in job.description, "description must be plain text"

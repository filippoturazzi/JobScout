"""Generic contract every registered source must satisfy.

``SOURCE_FIXTURES`` maps each source name to the captured fixture it is tested against, and
the entry's type says where the test boundary sits:

* ``HttpFixture`` for a source that calls an API with ``httpx``: the URL is mocked with
  ``respx`` and answers the fixture.
* ``JobSpyFixture`` for a source that drives python-jobspy: JobSpy owns its HTTP client, which
  ``respx`` cannot see, so ``scrape_jobs`` is patched to return the serialized capture.

Adding a source means adding one entry here; the same assertions then run against it.
"""

from typing import NamedTuple

import httpx
import pandas as pd
import pytest
import respx

from jobscout.config import Settings
from jobscout.sources import jobspy_base
from jobscout.sources.arbeitnow import BASE_URL as ARBEITNOW_URL
from jobscout.sources.base import JobSource, RawJob, SearchQuery
from jobscout.sources.himalayas import BASE_URL as HIMALAYAS_URL
from jobscout.sources.registry import SOURCE_FACTORIES
from jobscout.sources.remotive import BASE_URL as REMOTIVE_URL
from tests.conftest import load_fixture, load_jsonl


class HttpFixture(NamedTuple):
    url: str
    filename: str


class JobSpyFixture(NamedTuple):
    filename: str


SOURCE_FIXTURES: dict[str, HttpFixture | JobSpyFixture] = {
    "arbeitnow": HttpFixture(ARBEITNOW_URL, "arbeitnow_sample.json"),
    "himalayas": HttpFixture(HIMALAYAS_URL, "himalayas_search.json"),
    "remotive": HttpFixture(REMOTIVE_URL, "remotive_search.json"),
    "linkedin": JobSpyFixture("linkedin_sample.jsonl"),
    "indeed": JobSpyFixture("indeed_sample.jsonl"),
}


def _serve(fixture: HttpFixture | JobSpyFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    if isinstance(fixture, HttpFixture):
        respx.get(url__startswith=fixture.url).mock(
            return_value=httpx.Response(200, json=load_fixture(fixture.filename))
        )
        return

    def fake_scrape_jobs(**kwargs):
        frame = pd.DataFrame(load_jsonl(fixture.filename))
        frame.attrs = {"errors": {}, "warnings": {}}
        return frame

    monkeypatch.setattr(jobspy_base, "scrape_jobs", fake_scrape_jobs)


@pytest.mark.parametrize("name", sorted(SOURCE_FACTORIES))
@respx.mock
def test_source_contract(name, monkeypatch):
    assert name in SOURCE_FIXTURES, f"register a fixture for source {name!r}"
    _serve(SOURCE_FIXTURES[name], monkeypatch)
    source = SOURCE_FACTORIES[name](Settings(_env_file=None))

    assert isinstance(source, JobSource)
    # A search source fetches nothing without a term, so give it one.
    jobs = source.fetch(SearchQuery(keywords=["engineer"] if source.supports_search else []))

    assert jobs, "fixture must yield at least one job"
    ids = [j.external_id for j in jobs]
    assert len(ids) == len(set(ids)), "external_id must be unique within a fetch"
    for job in jobs:
        assert isinstance(job, RawJob)
        assert job.source == name
        assert job.external_id and job.title and job.url and job.description
        assert "<" not in job.description, "description must be plain text"

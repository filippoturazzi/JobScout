"""Hits the real Arbeitnow API. Run explicitly: ``uv run pytest -m integration``."""

import pytest

from jobscout.sources.arbeitnow import ArbeitnowSource
from jobscout.sources.base import SearchQuery

pytestmark = pytest.mark.integration


def test_live_fetch_returns_well_formed_jobs():
    jobs = ArbeitnowSource(max_pages=1).fetch(SearchQuery())
    assert len(jobs) > 50
    first = jobs[0]
    assert first.external_id and first.title and first.url.startswith("https://")
    assert "<" not in first.description

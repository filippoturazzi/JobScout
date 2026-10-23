"""Himalayas remote job board (https://himalayas.app). Free public API, no key.

Unlike Arbeitnow this API is searched server-side: ``GET /jobs/api/search?q=<term>&page=<n>``
(20 rows per page, no cursor). The parameter is ``q``; ``query``, ``search`` and ``keyword``
are silently ignored and return the whole unfiltered catalogue.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from jobscout import __version__
from jobscout.sources.base import RawJob, SearchQuery
from jobscout.sources.text import html_to_text

BASE_URL = "https://himalayas.app/jobs/api/search"
USER_AGENT = f"jobscout/{__version__} (+https://github.com/filippoturazzi/jobscout)"

log = logging.getLogger(__name__)


class HimalayasSource:
    name = "himalayas"
    supports_search = True

    def __init__(self, client: httpx.Client | None = None, max_pages: int = 1) -> None:
        self._client = client
        self._max_pages = max_pages

    def fetch(self, query: SearchQuery) -> list[RawJob]:
        if not query.keywords:
            return []
        if self._client is not None:
            return self._fetch_with(self._client, query)
        with httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT}) as client:
            return self._fetch_with(client, query)

    def _fetch_with(self, client: httpx.Client, query: SearchQuery) -> list[RawJob]:
        jobs: dict[str, RawJob] = {}
        for term in query.keywords:
            for page in range(1, self._max_pages + 1):
                response = client.get(BASE_URL, params={"q": term, "page": page})
                response.raise_for_status()
                items = response.json().get("jobs", [])
                for item in items:
                    if not isinstance(item, dict):
                        log.warning("himalayas: skipping malformed item %r: not a dict", item)
                        continue
                    try:
                        job = self._to_raw(item)
                    except (KeyError, TypeError, ValueError) as exc:
                        log.warning("himalayas: skipping malformed item: %s", exc)
                        continue
                    # The same posting can match several terms.
                    jobs.setdefault(job.external_id, job)
                if not items:
                    break
        return list(jobs.values())

    @staticmethod
    def _to_raw(item: dict[str, Any]) -> RawJob:
        # The API has no id field; ``guid`` is the posting's canonical URL.
        # A null guid or title is rejected by RawJob validation (a ValueError the caller
        # skips); no explicit guard is needed here.
        guid = item.get("guid")
        title = item.get("title")
        pub = item.get("pubDate")
        posted_at = datetime.fromtimestamp(pub, tz=UTC).replace(tzinfo=None) if pub else None
        # A salary is only comparable when annual; an hourly rate would read as pennies.
        annual = item.get("salaryPeriod") == "annual"
        description = html_to_text(item.get("description") or "") or (item.get("excerpt") or "")
        locations = [str(loc) for loc in item.get("locationRestrictions") or []]
        return RawJob(
            source="himalayas",
            external_id=guid,
            title=title,
            company=item.get("companyName") or "",
            location=", ".join(locations) or None,
            remote=True,
            url=guid,
            description=description,
            salary_min=item.get("minSalary") if annual else None,
            salary_max=item.get("maxSalary") if annual else None,
            salary_currency=item.get("currency") if annual else None,
            tags=list(item.get("seniority") or []),
            posted_at=posted_at,
            raw=item,
        )

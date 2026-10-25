"""Remotive remote job board (https://remotive.com). Free public API, no key.

Searched server-side: ``GET /api/remote-jobs?search=<term>``. The response is a single
page (no pagination) and every posting is remote. ``salary`` is free text
("$170k - $200k", "$50-$75 /hour", "OTE $25k - $35k"), so no numeric salary is derived
from it; the original string stays in ``raw``.
"""

import logging
from datetime import datetime
from typing import Any

import httpx

from jobscout import __version__
from jobscout.sources.base import RawJob, SearchQuery
from jobscout.sources.text import html_to_text

BASE_URL = "https://remotive.com/api/remote-jobs"
USER_AGENT = f"jobscout/{__version__} (+https://github.com/filippoturazzi/jobscout)"

log = logging.getLogger(__name__)


class RemotiveSource:
    name = "remotive"
    supports_search = True
    term_budget: int | None = None

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

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
            response = client.get(BASE_URL, params={"search": term})
            response.raise_for_status()
            for item in response.json().get("jobs", []):
                if not isinstance(item, dict):
                    log.warning("remotive: skipping malformed item %r: not a dict", item)
                    continue
                try:
                    job = self._to_raw(item)
                except (KeyError, TypeError, ValueError) as exc:
                    log.warning("remotive: skipping malformed item: %s", exc)
                    continue
                # The same posting can match several terms.
                jobs.setdefault(job.external_id, job)
        return list(jobs.values())

    @staticmethod
    def _to_raw(item: dict[str, Any]) -> RawJob:
        # The id is an integer, so it is stringified for ``external_id``; ``str(None)``
        # would silently mint the id "None", which validation cannot catch. A null title
        # or url, by contrast, is rejected by RawJob itself.
        job_id = item.get("id")
        if job_id is None:
            raise ValueError("missing id")
        raw_tags = item.get("tags") or []
        if not all(isinstance(tag, str) for tag in raw_tags):
            # One odd tag must cost that posting only, not the whole response.
            raise TypeError(f"non-string tag in {raw_tags!r}")
        published = item.get("publication_date")
        return RawJob(
            source="remotive",
            external_id=str(job_id),
            title=item.get("title"),
            company=item.get("company_name") or "",
            location=item.get("candidate_required_location") or None,
            remote=True,
            url=item.get("url"),
            description=html_to_text(item.get("description") or ""),
            tags=[tag.strip() for tag in raw_tags if tag.strip()],
            posted_at=datetime.fromisoformat(published) if published else None,
            raw=item,
        )

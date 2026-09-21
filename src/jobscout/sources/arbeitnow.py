"""Arbeitnow job board (https://www.arbeitnow.com). Free public API, no key.

Terms (from the API's own ``meta.terms``): do not abuse; link back to arbeitnow.com.
Jobs are ordered by ``created_at`` desc and paginated with ``?page=N`` (250 per page).
"""

import html
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from jobscout import __version__
from jobscout.sources.base import RawJob, SearchQuery
from jobscout.sources.text import html_to_text

BASE_URL = "https://www.arbeitnow.com/api/job-board-api"
USER_AGENT = f"jobscout/{__version__} (+https://github.com/filippoturazzi/jobscout)"

log = logging.getLogger(__name__)


class ArbeitnowSource:
    name = "arbeitnow"

    def __init__(self, client: httpx.Client | None = None, max_pages: int = 2) -> None:
        self._client = client
        self._max_pages = max_pages

    def fetch(self, query: SearchQuery) -> list[RawJob]:
        if self._client is not None:
            return self._fetch_with(self._client, query)
        with httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT}) as client:
            return self._fetch_with(client, query)

    def _fetch_with(self, client: httpx.Client, query: SearchQuery) -> list[RawJob]:
        jobs: list[RawJob] = []
        page = 1
        while page <= self._max_pages:
            response = client.get(BASE_URL, params={"page": page})
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("data", []):
                if not isinstance(item, dict):
                    log.warning("arbeitnow: skipping malformed item %r: not a dict", item)
                    continue
                try:
                    jobs.append(self._to_raw(item))
                except (KeyError, TypeError, ValueError) as exc:
                    log.warning("arbeitnow: skipping malformed item %r: %s", item.get("slug"), exc)
            if not payload.get("links", {}).get("next"):
                break
            page += 1
        return jobs

    @staticmethod
    def _to_raw(item: dict[str, Any]) -> RawJob:
        created = item.get("created_at")
        posted_at = (
            datetime.fromtimestamp(created, tz=UTC).replace(tzinfo=None) if created else None
        )
        return RawJob(
            source="arbeitnow",
            external_id=item["slug"],
            title=html.unescape(item["title"]),
            company=html.unescape(item.get("company_name") or ""),
            location=item.get("location") or None,
            remote=bool(item.get("remote", False)),
            url=item["url"],
            description=html_to_text(item.get("description", "")),
            tags=list(item.get("tags") or []) + list(item.get("job_types") or []),
            posted_at=posted_at,
            raw=item,
        )

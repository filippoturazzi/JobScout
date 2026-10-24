"""Shared adapter over ``python-jobspy`` (https://github.com/speedyapply/JobSpy).

Unlike every other source this one does not call a documented public API with ``httpx``: it
drives a library that scrapes LinkedIn, Indeed and Google Jobs. What was verified upstream:

* ``scrape_jobs`` is synchronous and returns a pandas DataFrame (about 35 columns, from
  ``JobPost``). Columns are read defensively here, because a site may leave any of them out.
* A blocked or failing site does **not** raise. Each site is scraped in a thread, its
  exception is captured, and the failure is reported in ``frame.attrs["errors"]`` while the
  call returns an empty DataFrame. Without reading ``attrs`` every block would be recorded as
  "0 jobs, no errors", so ``fetch`` raises ``SourceBlocked`` instead.
* ``attrs["warnings"]`` carries non-fatal problems; they are exposed through ``warnings``,
  which ``pipeline.search`` drains into the run's errors.
* Missing values arrive as ``NaN``, not ``None``, and a serialized capture turns bools and
  dates into strings. Both are tolerated.

Tests patch ``scrape_jobs`` rather than using ``respx``: JobSpy owns its HTTP client, which
``respx`` cannot see, so the test boundary for this source kind sits one level further out.
"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

import pandas as pd
from jobspy import scrape_jobs

from jobscout.config import Settings
from jobscout.sources.base import RawJob, SearchQuery
from jobscout.sources.text import html_to_text

log = logging.getLogger(__name__)


class SourceBlocked(RuntimeError):
    """JobSpy reported a per-site error (rate limit, block, captcha) instead of raising."""


def _clean(value: Any) -> Any:
    """``None`` for any missing value, including pandas' ``NaN`` and ``NaT``."""
    if value is None:
        return None
    try:
        return None if pd.isna(value) else value
    except (TypeError, ValueError):  # array-like cell: not a scalar, so not "missing"
        return value


def _text(row: dict[str, Any], column: str) -> str | None:
    value = _clean(row.get(column))
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool(value: Any) -> bool:
    value = _clean(value)
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _int(value: Any) -> int | None:
    value = _clean(value)
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> datetime | None:
    value = _clean(value)
    if value is None:
        return None
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(stamp):
        return None
    result: datetime = (stamp.tz_localize(None) if stamp.tzinfo else stamp).to_pydatetime()
    return result


def _json_safe(row: dict[str, Any]) -> dict[str, Any]:
    """The row as plain JSON values (``raw`` is stored as JSON)."""
    safe: dict[str, Any] = json.loads(
        json.dumps({k: _clean(v) for k, v in row.items()}, default=str)
    )
    return safe


def to_raw_jobs(frame: pd.DataFrame, source: str) -> list[RawJob]:
    jobs: list[RawJob] = []
    for row in frame.to_dict(orient="records"):
        title = _text(row, "title")
        url = _text(row, "job_url")
        if title is None or url is None:
            log.warning("%s: skipping a row without a title or url", source)
            continue
        # A salary is only comparable when annual; an hourly rate would read as pennies
        # (same rule as himalayas). Do not "fix" this with enforce_annual_salary=True: JobSpy
        # would then multiply the rate into a figure the employer never stated, and JobScout
        # would show it as the posting's salary. The stated figures stay in ``raw``.
        annual = (_text(row, "interval") or "").lower() == "yearly"
        try:
            jobs.append(
                RawJob(
                    source=source,
                    external_id=_text(row, "id") or hashlib.sha256(url.encode()).hexdigest(),
                    title=title,
                    company=_text(row, "company") or "",
                    location=_text(row, "location"),
                    remote=_bool(row.get("is_remote")),
                    url=url,
                    description=html_to_text(_text(row, "description") or ""),
                    salary_min=_int(row.get("min_amount")) if annual else None,
                    salary_max=_int(row.get("max_amount")) if annual else None,
                    salary_currency=_text(row, "currency") if annual else None,
                    posted_at=_datetime(row.get("date_posted")),
                    raw=_json_safe(row),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("%s: skipping malformed row: %s", source, exc)
    return jobs


def _messages(report: Any) -> list[str]:
    if not report:
        return []
    if isinstance(report, dict):
        return [f"{site}: {message}" for site, message in report.items()]
    return [str(item) for item in report]


class JobSpySource:
    """One JobSpy site. Subclasses set ``name``/``site`` and override ``search_kwargs``."""

    name = "jobspy"
    site = ""
    supports_search = True
    fetch_description = False

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.term_budget: int | None = settings.jobspy_max_terms
        self.warnings: list[str] = []

    def search_kwargs(self, query: SearchQuery) -> dict[str, object]:
        """The per-site arguments. The composer passes one term at a time."""
        return {"search_term": query.keywords[0]}

    def fetch(self, query: SearchQuery) -> list[RawJob]:
        self.warnings = []
        if not query.keywords:
            return []
        params: dict[str, Any] = {
            "site_name": [self.site],
            "results_wanted": self._settings.jobspy_results_wanted,
            "hours_old": self._settings.jobspy_hours_old,
            "proxies": self._settings.jobspy_proxy_list or None,
            "description_format": "markdown",
            "fetch_description": self.fetch_description,
            **self.search_kwargs(query),
        }
        frame = scrape_jobs(**params)
        self.warnings.extend(_messages(frame.attrs.get("warnings")))
        errors = _messages(frame.attrs.get("errors"))
        if errors:
            raise SourceBlocked("; ".join(errors))
        return to_raw_jobs(frame, self.name)

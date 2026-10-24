"""The JobSpy adapter.

Every other source is tested with ``respx`` against an HTTP fixture. JobSpy makes its own
HTTP calls inside a thread pool, where ``respx`` cannot see them, so for this source kind the
test boundary moves one level out: these tests patch ``scrape_jobs`` itself and feed the
adapter DataFrames built from a real, serialized capture (``linkedin_sample.jsonl``).
The capture has 14 columns; a live frame has about 35, so the adapter must not assume any.
"""

import math
from datetime import date, datetime

import pandas as pd
import pytest

from jobscout.config import Settings
from jobscout.sources import jobspy_base
from jobscout.sources.base import SearchQuery
from jobscout.sources.jobspy_base import JobSpySource, SourceBlocked, to_raw_jobs
from tests.conftest import load_jsonl


def _row(**overrides):
    row = {
        "id": "li-1",
        "site": "linkedin",
        "job_url": "https://x/0",
        "title": "Python Developer",
        "company": "Acme",
        "description": "Build things.",
    }
    row.update(overrides)
    return row


def _frame(rows, errors=None, warnings=None):
    frame = pd.DataFrame(rows)
    frame.attrs = {"errors": errors or {}, "warnings": warnings or {}}
    return frame


def _never_called(**kwargs):
    raise AssertionError("scrape_jobs must not be called")


def test_a_captured_row_becomes_a_raw_job():
    jobs = to_raw_jobs(_frame(load_jsonl("linkedin_sample.jsonl")), "linkedin")
    assert len(jobs) == 5
    assert all(j.source == "linkedin" and j.url and j.description for j in jobs)
    assert all("<" not in j.description for j in jobs)
    assert jobs[0].posted_at == datetime(2026, 10, 14)
    assert jobs[0].remote is False


def test_a_row_without_an_id_falls_back_to_the_url():
    [job] = to_raw_jobs(_frame([_row(id=None, job_url="https://x/1")]), "linkedin")
    assert job.external_id and job.external_id != "None"


def test_two_rows_without_ids_do_not_collide():
    jobs = to_raw_jobs(
        _frame([_row(id=None, job_url="https://x/1"), _row(id=None, job_url="https://x/2")]),
        "linkedin",
    )
    assert len({j.external_id for j in jobs}) == 2


def test_a_nan_id_counts_as_missing():
    [job] = to_raw_jobs(_frame([_row(id=math.nan)]), "linkedin")
    assert job.external_id != "nan"
    assert len(job.external_id) == 64


def test_a_row_without_a_company_is_kept():
    [job] = to_raw_jobs(_frame([_row(company=None)]), "linkedin")
    assert job.company == ""


def test_a_row_without_a_description_is_kept():
    [job] = to_raw_jobs(_frame([_row(description=None)]), "linkedin")
    assert job.description == ""


def test_a_row_without_a_title_or_url_is_skipped_and_the_others_are_kept():
    jobs = to_raw_jobs(
        _frame([_row(title=None), _row(id="good", job_url="https://x/good"), _row(job_url=None)]),
        "linkedin",
    )
    assert [j.external_id for j in jobs] == ["good"]


def test_columns_missing_from_the_frame_are_tolerated():
    [job] = to_raw_jobs(_frame([{"title": "T", "job_url": "https://x/1"}]), "linkedin")
    assert job.title == "T" and job.company == "" and job.posted_at is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (False, False), ("True", True), ("False", False), (math.nan, False)],
)
def test_is_remote_tolerates_bools_strings_and_nan(value, expected):
    [job] = to_raw_jobs(_frame([_row(is_remote=value)]), "linkedin")
    assert job.remote is expected


@pytest.mark.parametrize("value", [date(2026, 10, 14), "2026-10-14", pd.Timestamp("2026-10-14")])
def test_date_posted_tolerates_dates_strings_and_timestamps(value):
    [job] = to_raw_jobs(_frame([_row(date_posted=value)]), "linkedin")
    assert job.posted_at == datetime(2026, 10, 14)


def test_an_unparseable_or_nan_date_is_none():
    jobs = to_raw_jobs(
        _frame([_row(date_posted="soon"), _row(job_url="https://x/2", date_posted=math.nan)]),
        "linkedin",
    )
    assert [j.posted_at for j in jobs] == [None, None]


def test_salary_is_mapped_and_nan_becomes_none():
    jobs = to_raw_jobs(
        _frame(
            [
                _row(min_amount=50000.0, max_amount=70000.0, currency="USD", interval="yearly"),
                _row(job_url="https://x/2", min_amount=math.nan, max_amount=math.nan),
            ]
        ),
        "linkedin",
    )
    assert (jobs[0].salary_min, jobs[0].salary_max, jobs[0].salary_currency) == (
        50000,
        70000,
        "USD",
    )
    assert jobs[1].salary_min is None and jobs[1].salary_max is None


def test_markup_in_a_description_is_flattened():
    [job] = to_raw_jobs(_frame([_row(description="<p>Hello <b>there</b></p>")]), "linkedin")
    assert "<" not in job.description and "Hello" in job.description


def test_raw_is_json_safe():
    [job] = to_raw_jobs(
        _frame([_row(date_posted=date(2026, 10, 14), min_amount=math.nan)]), "linkedin"
    )
    assert job.raw["id"] == "li-1"
    assert job.raw["date_posted"] == "2026-10-14"
    assert job.raw["min_amount"] is None


def test_a_blocked_site_raises_instead_of_returning_nothing(monkeypatch):
    monkeypatch.setattr(
        jobspy_base, "scrape_jobs", lambda **kw: _frame([], errors={"linkedin": "429"})
    )
    with pytest.raises(SourceBlocked, match="429"):
        JobSpySource(Settings(_env_file=None)).fetch(SearchQuery(keywords=["python"]))


def test_the_settings_reach_scrape_jobs(monkeypatch):
    seen = {}
    monkeypatch.setattr(jobspy_base, "scrape_jobs", lambda **kw: seen.update(kw) or _frame([]))
    JobSpySource(Settings(_env_file=None, jobspy_proxies="localhost")).fetch(
        SearchQuery(keywords=["python"])
    )
    assert seen["results_wanted"] == 10 and seen["hours_old"] == 168
    assert seen["proxies"] == ["localhost"]
    assert seen["description_format"] == "markdown"
    assert seen["search_term"] == "python"


def test_the_site_and_the_description_flag_reach_scrape_jobs(monkeypatch):
    class _Described(JobSpySource):
        name = site = "linkedin"
        fetch_description = True

    seen = {}
    monkeypatch.setattr(jobspy_base, "scrape_jobs", lambda **kw: seen.update(kw) or _frame([]))
    _Described(Settings(_env_file=None)).fetch(SearchQuery(keywords=["python"]))
    assert seen["site_name"] == ["linkedin"]
    assert seen["fetch_description"] is True


def test_no_keyword_means_no_call(monkeypatch):
    monkeypatch.setattr(jobspy_base, "scrape_jobs", _never_called)
    assert JobSpySource(Settings(_env_file=None)).fetch(SearchQuery()) == []


def test_fetch_returns_the_mapped_rows(monkeypatch):
    rows = load_jsonl("linkedin_sample.jsonl")
    monkeypatch.setattr(jobspy_base, "scrape_jobs", lambda **kw: _frame(rows))
    source = JobSpySource(Settings(_env_file=None))
    source.name = "linkedin"
    assert len(source.fetch(SearchQuery(keywords=["python"]))) == 5


def test_term_budget_comes_from_settings():
    assert JobSpySource(Settings(_env_file=None, jobspy_max_terms=2)).term_budget == 2


def test_warnings_are_reset_each_fetch_and_filled_from_the_frame(monkeypatch):
    frames = iter([_frame([], warnings={"linkedin": "slow"}), _frame([])])
    monkeypatch.setattr(jobspy_base, "scrape_jobs", lambda **kw: next(frames))
    source = JobSpySource(Settings(_env_file=None))
    source.fetch(SearchQuery(keywords=["python"]))
    assert source.warnings and "slow" in source.warnings[0]
    source.fetch(SearchQuery(keywords=["python"]))
    assert source.warnings == []


@pytest.mark.parametrize("interval", ["hourly", "daily", "weekly", "monthly", None, math.nan])
def test_a_non_annual_salary_is_left_empty(interval):
    [job] = to_raw_jobs(
        _frame([_row(min_amount=30.0, max_amount=45.0, currency="USD", interval=interval)]),
        "linkedin",
    )
    assert job.salary_min is None and job.salary_max is None and job.salary_currency is None
    assert job.raw["min_amount"] == 30.0


def test_a_salary_without_an_interval_column_is_left_empty():
    [job] = to_raw_jobs(_frame([_row(min_amount=50000.0, max_amount=70000.0)]), "linkedin")
    assert job.salary_min is None


def test_a_warning_added_while_building_arguments_survives_the_scrape(monkeypatch):
    class Warns(JobSpySource):
        def search_kwargs(self, query):
            self.warnings.append("from the subclass")
            return super().search_kwargs(query)

    monkeypatch.setattr(
        jobspy_base, "scrape_jobs", lambda **kw: _frame([_row()], warnings={"linkedin": "slow"})
    )
    source = Warns(Settings(_env_file=None))
    source.fetch(SearchQuery(keywords=["python"]))
    assert source.warnings == ["from the subclass", "linkedin: slow"]

import pytest

from jobscout.models import Job
from jobscout.pipeline.logos import company_logo_of


def job_with(raw: dict) -> Job:
    return Job(
        source="fake",
        external_id="1",
        title="Engineer",
        company="Acme",
        url="https://x/1",
        description="d",
        content_hash="h",
        raw=raw,
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"companyLogo": "https://cdn-images.himalayas.app/abc"},  # Himalayas
        {"company_logo": "https://cdn-images.himalayas.app/abc"},  # Remotive, JobSpy
        {"company_logo_url": "https://cdn-images.himalayas.app/abc"},  # Remotive's other key
    ],
)
def test_reads_the_logo_from_each_boards_key(raw):
    assert company_logo_of(job_with(raw)) == "https://cdn-images.himalayas.app/abc"


def test_first_key_with_a_url_wins():
    raw = {"company_logo": "", "company_logo_url": "https://remotive.com/job/1/logo"}
    assert company_logo_of(job_with(raw)) == "https://remotive.com/job/1/logo"


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        12,
        float("nan"),  # pandas' empty cell, as JobSpy rows may carry it
        "http://insecure.example/logo.png",
        "javascript:alert(1)",
        "data:image/png;base64,AAAA",
        "//cdn.example/logo.png",
        "not a url",
    ],
)
def test_no_logo_unless_it_is_an_https_url(value):
    assert company_logo_of(job_with({"company_logo": value})) is None


def test_no_logo_when_the_board_sends_none():
    assert company_logo_of(job_with({})) is None

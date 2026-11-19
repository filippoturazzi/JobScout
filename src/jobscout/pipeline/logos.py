"""The company's logo, read from the board's own payload (``Job.raw``).

Every default board sends one: Himalayas as ``companyLogo``, Remotive as ``company_logo`` (and
``company_logo_url``), LinkedIn and Indeed through JobSpy as ``company_logo``. Reading it from
``raw`` instead of a column means jobs fetched before this existed get their logo too.
"""

from urllib.parse import urlsplit

from jobscout.models import Job

LOGO_KEYS = ("companyLogo", "company_logo", "company_logo_url")


def company_logo_of(job: Job) -> str | None:
    """The first https logo URL in the job's payload, or None (the page shows the initial)."""
    for key in LOGO_KEYS:
        value = job.raw.get(key)
        if isinstance(value, str) and _is_https_url(value.strip()):
            return value.strip()
    return None


def _is_https_url(value: str) -> bool:
    # https only: the page loads it as an <img>, so no other scheme and no mixed content.
    parts = urlsplit(value)
    return parts.scheme == "https" and bool(parts.netloc)

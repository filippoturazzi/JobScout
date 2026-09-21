"""Cheap, deterministic pre-filter applied before (stage 2) semantic matching.

Coarse by design: its job is to drop obvious non-candidates, not to rank.
"""

import re
from collections.abc import Iterable

from jobscout.models import Job, UserPreferences

_TOKEN_RE = re.compile(r"(?:[^\W_]|[+#.])+")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens in order; trailing periods dropped, leading dots kept (".net")."""
    tokens = (token.rstrip(".") for token in _TOKEN_RE.findall(text.lower()))
    return [token for token in tokens if token]


def _contains_sequence(haystack: list[str], needle: list[str]) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    return any(
        haystack[i : i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1)
    )


def _passes_exclusions(job: Job, prefs: UserPreferences) -> bool:
    title_tokens = tokenize(job.title)
    tag_tokens = [tokenize(tag) for tag in job.tags]
    for keyword in prefs.excluded_keywords:
        needle = tokenize(keyword)
        if not needle:
            continue
        if _contains_sequence(title_tokens, needle) or needle in tag_tokens:
            return False
    return True


def _passes_work_mode(job: Job, prefs: UserPreferences) -> bool:
    modes = {m.lower() for m in prefs.work_modes}
    if not modes:
        return True
    if job.remote:
        return "remote" in modes
    return bool(modes & {"hybrid", "onsite"})


def _passes_region(job: Job, prefs: UserPreferences) -> bool:
    if not prefs.regions or job.remote:
        return True
    segments = [tokenize(segment) for segment in (job.location or "").split(",")]
    for region in prefs.regions:
        needle = tokenize(region)
        if needle and any(_contains_sequence(segment, needle) for segment in segments):
            return True
    return False


def _passes_titles(job: Job, prefs: UserPreferences) -> bool:
    if not prefs.titles:
        return True
    title_words = set(tokenize(job.title))
    for preferred in prefs.titles:
        words = set(tokenize(preferred))
        if words and words <= title_words:
            return True
    return False


def job_matches_preferences(job: Job, prefs: UserPreferences) -> bool:
    return (
        _passes_exclusions(job, prefs)
        and _passes_work_mode(job, prefs)
        and _passes_region(job, prefs)
        and _passes_titles(job, prefs)
    )


def filter_jobs(jobs: Iterable[Job], prefs: UserPreferences) -> list[Job]:
    return [job for job in jobs if job_matches_preferences(job, prefs)]

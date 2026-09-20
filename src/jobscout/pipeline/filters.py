"""Cheap, deterministic pre-filter applied before (stage 2) semantic matching.

Coarse by design: its job is to drop obvious non-candidates, not to rank.
"""

import re
from collections.abc import Iterable

from jobscout.models import Job, UserPreferences

_WORD_RE = re.compile(r"[a-z0-9+#.]+")


def _words(text: str) -> set[str]:
    tokens = (token.rstrip(".") for token in _WORD_RE.findall(text.lower()))
    return {token for token in tokens if token}


def _passes_exclusions(job: Job, prefs: UserPreferences) -> bool:
    haystack = " ".join([job.title, *job.tags]).lower()
    return not any(kw.lower() in haystack for kw in prefs.excluded_keywords if kw.strip())


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
    location = (job.location or "").lower()
    return any(region.lower() in location for region in prefs.regions if region.strip())


def _passes_titles(job: Job, prefs: UserPreferences) -> bool:
    if not prefs.titles:
        return True
    title_words = _words(job.title)
    return any(_words(t) and _words(t) <= title_words for t in prefs.titles)


def job_matches_preferences(job: Job, prefs: UserPreferences) -> bool:
    return (
        _passes_exclusions(job, prefs)
        and _passes_work_mode(job, prefs)
        and _passes_region(job, prefs)
        and _passes_titles(job, prefs)
    )


def filter_jobs(jobs: Iterable[Job], prefs: UserPreferences) -> list[Job]:
    return [job for job in jobs if job_matches_preferences(job, prefs)]

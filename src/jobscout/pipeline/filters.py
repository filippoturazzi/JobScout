"""Cheap, deterministic pre-filter applied before (stage 2) semantic matching.

Coarse by design: its job is to drop obvious non-candidates, not to rank.
"""

import re
from collections.abc import Iterable

from jobscout.models import Job, UserPreferences
from jobscout.sources.regions import countries_in, country_of
from jobscout.sources.text import fold

_TOKEN_RE = re.compile(r"(?:[^\W_]|[+#.])+")

# All of these read folded text (lower case, no accents). A title or location is short enough
# that the bare word is the work mode, apart from the technology that shares its name. A
# description is not: "hybrid cloud" and "on-site interviews" say nothing about where the job
# is, so there it takes a phrase that does.
_HYBRID_SHORT = re.compile(
    r"\bhybrid\b(?!\s+(?:cloud|mobile|apps?|infrastructure|search|rag))"
    r"|(?<!nuvem )\bhibrid[oa]\b"
)
_ONSITE_SHORT = re.compile(r"\bon[- ]?site\b|\bpresencial\b|\bin[- ]office\b")
_LABEL = (
    r"\b(?:work|working|workplace|location|arrangement|schedule|modelo|regime|trabalho|formato"
    r"|modalidade|atuacao|jornada)(?:\s+(?:type|mode|model|de\s+\w+))?\s*[:\-\u2013]?\s*"
)
_HYBRID_LONG = re.compile(
    r"\bhybrid\s+(?:role|position|job|work|working|model|schedule|setup|arrangement|policy)\b"
    rf"|{_LABEL}(?:hybrid|hibrid[oa])\b"
)
_ONSITE_LONG = re.compile(
    r"\b(?:fully|100\s*%?)\s*(?:on[- ]?site|in[- ]office|presencial)\b"
    r"|\b(?:on[- ]?site|in[- ]office)\s+(?:role|position|job|work)\b"
    rf"|{_LABEL}(?:on[- ]?site|presencial)\b"
)


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


def _stated_on_premises_mode(job: Job) -> str | None:
    """ "hybrid" or "onsite" when a non-remote posting says which it is, else ``None``.

    Boards report only remote or not, so this reads the posting's words. Hybrid is checked
    first: a hybrid posting often describes its days on site too.
    """
    short = fold(f"{job.title} | {job.location or ''}")
    if _HYBRID_SHORT.search(short):
        return "hybrid"
    if _ONSITE_SHORT.search(short):
        return "onsite"
    description = fold(job.description)
    if _HYBRID_LONG.search(description):
        return "hybrid"
    if _ONSITE_LONG.search(description):
        return "onsite"
    return None


def _passes_work_mode(job: Job, prefs: UserPreferences) -> bool:
    modes = {m.lower() for m in prefs.work_modes}
    if not modes:
        return True
    if job.remote:
        return "remote" in modes
    stated = _stated_on_premises_mode(job)
    if stated is not None:
        return stated in modes
    # The posting does not say, and hiding a job takes evidence.
    return bool(modes & {"hybrid", "onsite"})


def _same_region(a: str, b: str) -> bool:
    country = country_of(a)
    if country is not None:
        return country == country_of(b)
    return bool(fold(a)) and fold(a) == fold(b)


def _location_is_in(location: str, region: str) -> bool:
    country = country_of(region)
    if country is not None:
        return country in countries_in(location)
    needle = tokenize(fold(region))
    return bool(needle) and _contains_sequence(tokenize(fold(location)), needle)


def _countries_of(regions: list[str]) -> set[str]:
    return {country for country in map(country_of, regions) if country is not None}


def _in_excluded_region(job: Job, named: frozenset[str], excluded: set[str]) -> bool:
    """True when the job is known to be only in countries the user ruled out.

    A posting open to several places stays in as long as one of them is not ruled out, and
    one that names no country counts as where its source was searched, if that is recorded.
    """
    if named:
        return named <= excluded
    searched = job.raw.get("searched_region")
    return isinstance(searched, str) and country_of(searched) in excluded


def _passes_region(job: Job, prefs: UserPreferences) -> bool:
    location = job.location or ""
    named = countries_in(location)
    if _in_excluded_region(job, named, _countries_of(prefs.excluded_regions)):
        return False
    if not prefs.regions:
        return True
    if job.remote:
        # On a remote posting the location is who may apply: "United States" is closed to
        # someone in Brazil, while "Worldwide" or nothing at all may not be. It is rejected
        # only on evidence: it names places, and we know the user's countries, and none match.
        wanted = _countries_of(prefs.regions)
        return not wanted or not named or bool(named & wanted)
    searched = job.raw.get("searched_region")
    # The search record vouches only for a location that names no country ("Greater Curitiba").
    # One that names another country wins over it: a site that ignored the search location
    # answers with postings from elsewhere, and saying they are in the region would be a lie.
    vouched = isinstance(searched, str) and not named
    for region in prefs.regions:
        if vouched and _same_region(str(searched), region):
            return True
        if location and _location_is_in(location, region):
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

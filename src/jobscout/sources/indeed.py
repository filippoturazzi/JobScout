"""Indeed, through JobSpy (see ``jobspy_base``). No key; a proxy is optional.

Verified against a live capture (``tests/fixtures/indeed_sample.jsonl``, 5 rows from the
Brazilian site): search results already include the description, so ``fetch_description`` stays
off. Unlike LinkedIn, Indeed is country-scoped: ``country_indeed`` picks the domain, and it
only accepts the values in JobSpy's ``Country`` enum. There is no worldwide value (Indeed is
partitioned by domain, and python-jobspy 1.4.1 raises on one), so with no recognised region
this source does not search.
"""

import unicodedata

from jobscout.sources.base import RawJob, SearchQuery
from jobscout.sources.jobspy_base import JobSpySource

# Normalised region name (lowercase, no accents) -> JobSpy ``Country`` value.
_COUNTRIES = {
    "brasil": "brazil",
    "brazil": "brazil",
    "br": "brazil",
    "portugal": "portugal",
    "pt": "portugal",
    "espana": "spain",
    "spain": "spain",
    "es": "spain",
    "usa": "usa",
    "us": "usa",
    "united states": "usa",
    "united states of america": "usa",
    "estados unidos": "usa",
    "uk": "uk",
    "gb": "uk",
    "united kingdom": "uk",
    "reino unido": "uk",
    "germany": "germany",
    "deutschland": "germany",
    "alemanha": "germany",
    "alemania": "germany",
    "de": "germany",
    "canada": "canada",
}
# The two-letter entries are ISO 3166-1 alpha-2 codes. "ca" is deliberately absent: a user
# typing it is as likely to mean California, and a quiet search of the wrong market is worse
# than none. Spelling "Canada" out works.


def _normalise(region: str) -> str:
    decomposed = unicodedata.normalize("NFKD", region)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


def country_for(regions: list[str]) -> tuple[str | None, str | None]:
    """The JobSpy country for the first recognised region, and a value it had to ignore.

    Only the first recognised region is used: searching every region times every term would
    multiply the block risk by the number of regions. Returns ``(None, value)`` when regions
    were given but none is recognised (``value`` is the first one), and ``(None, None)`` when
    there are none.
    """
    given = [region for region in regions if region.strip()]
    for region in given:
        country = _COUNTRIES.get(_normalise(region))
        if country is not None:
            return country, None
    return None, (given[0] if given else None)


class IndeedSource(JobSpySource):
    name = "indeed"
    site = "indeed"

    def search_kwargs(self, query: SearchQuery) -> dict[str, object]:
        country, _ = country_for(query.locations)
        return {**super().search_kwargs(query), "country_indeed": country}

    def fetch(self, query: SearchQuery) -> list[RawJob]:
        country, ignored = country_for(query.locations)
        if country is None and query.keywords:
            # Deliberately no fallback market. Indeed has no worldwide search, and letting
            # JobSpy default to the US would fill the corpus with postings the user never
            # asked for (the irrelevant-corpus problem stage 5 exists to fix) and spend their
            # embedding budget on them. Region is a user preference; it is never invented in
            # code. Searching nothing and saying so is the truthful outcome.
            reason = (
                f"region {ignored!r} is not one Indeed supports"
                if ignored is not None
                else "no region is set"
            )
            self.warnings = [f"indeed: not searched, {reason}; set a region in your preferences"]
            return []
        return super().fetch(query)

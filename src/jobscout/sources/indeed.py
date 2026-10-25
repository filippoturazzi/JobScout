"""Indeed, through JobSpy (see ``jobspy_base``). No key; a proxy is optional.

Verified against a live capture (``tests/fixtures/indeed_sample.jsonl``, 5 rows from the
Brazilian site): search results already include the description, so ``fetch_description`` stays
off. Unlike LinkedIn, Indeed is country-scoped: ``country_indeed`` picks the domain, and it
only accepts the values in JobSpy's ``Country`` enum. There is no worldwide value (Indeed is
partitioned by domain, and python-jobspy 1.4.1 raises on one), so with no recognised region
this source does not search.
"""

from jobscout.sources.base import RawJob, SearchQuery
from jobscout.sources.jobspy_base import JobSpySource
from jobscout.sources.regions import country_of


def country_for(regions: list[str]) -> tuple[str | None, str | None]:
    """The JobSpy country for the first recognised region, and a value it had to ignore.

    Only the first recognised region is used: searching every region times every term would
    multiply the block risk by the number of regions. Returns ``(None, value)`` when regions
    were given but none is recognised (``value`` is the first one), and ``(None, None)`` when
    there are none.
    """
    given = [region for region in regions if region.strip()]
    for region in given:
        country = country_of(region)
        if country is not None:
            return country, None
    return None, (given[0] if given else None)


class IndeedSource(JobSpySource):
    name = "indeed"
    site = "indeed"

    def searched_region(self, query: SearchQuery) -> str | None:
        """The first region Indeed recognises, the one ``country_indeed`` is set from."""
        return next((r.strip() for r in query.locations if country_of(r) is not None), None)

    def search_kwargs(self, query: SearchQuery) -> dict[str, object]:
        country, _ = country_for(query.locations)
        kwargs = super().search_kwargs(query)
        # No ``location`` for Indeed: ``country_indeed`` already picks the market, and JobSpy
        # turns a location into ``radius: 50 MILES`` around whatever it geocodes
        # (``jobspy/indeed/constant.py``'s ``default_distance``), which would shrink a
        # country-wide preference to one metro area and silently drop the rest of the country.
        # ``is_remote`` is kept: Indeed does filter on it (``_build_filters``).
        kwargs.pop("location", None)
        kwargs["country_indeed"] = country
        return kwargs

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

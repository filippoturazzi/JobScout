"""Indeed, through JobSpy (see ``jobspy_base``). No key; a proxy is optional.

Verified against a live capture (``tests/fixtures/indeed_sample.jsonl``, 5 rows from the
Brazilian site): search results already include the description, so ``fetch_description`` stays
off. Unlike LinkedIn, Indeed is country-scoped: ``country_indeed`` picks the domain, and it
only accepts the values in JobSpy's ``Country`` enum. ``"worldwide"`` is not one of them in
python-jobspy 1.4.1 (validation raises), so it is only this module's name for "no recognised
region": the argument is then left out and JobSpy falls back to its own default.
"""

import unicodedata

from jobscout.sources.base import SearchQuery
from jobscout.sources.jobspy_base import JobSpySource

WORLDWIDE = "worldwide"

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
    "ca": "canada",
}


def _normalise(region: str) -> str:
    decomposed = unicodedata.normalize("NFKD", region)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


def country_for(regions: list[str]) -> tuple[str, str | None]:
    """The JobSpy country for the first recognised region, and a value it had to ignore.

    Only the first recognised region is used: searching every region times every term would
    multiply the block risk by the number of regions. Returns ``("worldwide", value)`` when
    regions were given but none is recognised (``value`` is the first one), and
    ``("worldwide", None)`` when there are none.
    """
    for region in regions:
        country = _COUNTRIES.get(_normalise(region))
        if country is not None:
            return country, None
    return WORLDWIDE, (regions[0] if regions else None)


class IndeedSource(JobSpySource):
    name = "indeed"
    site = "indeed"

    def search_kwargs(self, query: SearchQuery) -> dict[str, object]:
        kwargs = super().search_kwargs(query)
        country, ignored = country_for(query.locations)
        if country != WORLDWIDE:
            kwargs["country_indeed"] = country
        if ignored is not None:
            # Rebuilt from the stored regions on every term, so it survives the per-fetch
            # reset of ``warnings`` and reaches the run's errors.
            self.warnings.append(
                f"indeed: region {ignored!r} is not one Indeed supports, so it was searched "
                "without a country"
            )
        return kwargs

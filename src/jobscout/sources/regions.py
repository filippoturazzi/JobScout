"""Country names a user may type as a region, shared by the sources and the candidate filter.

The keys are folded (``text.fold``); the values are JobSpy ``Country`` values, which double as
this project's country identifiers. A user writes "Brasil", a board writes "Brazil" or "BR",
and all three must mean one country to both the search and the filter.
"""

from jobscout.sources.text import fold

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

# How each country is written to a site that geocodes free text. LinkedIn reads "Brazil" but
# not "Brasil": a live search for "Brasil" returned five US postings.
_ENGLISH = {
    "brazil": "Brazil",
    "portugal": "Portugal",
    "spain": "Spain",
    "usa": "United States",
    "uk": "United Kingdom",
    "germany": "Germany",
    "canada": "Canada",
}


def country_of(region: str) -> str | None:
    """The country a region names, or ``None`` when it names none this table knows."""
    return _COUNTRIES.get(fold(region))


def english_name(country: str) -> str:
    """``country`` the way an English-language site writes it."""
    return _ENGLISH[country]


def countries() -> set[str]:
    return set(_COUNTRIES.values())


def names_of(country: str) -> tuple[list[str], list[str]]:
    """Every folded way of writing ``country``: its names, then its two-letter codes."""
    names = [name for name, value in _COUNTRIES.items() if value == country]
    return [n for n in names if len(n) > 2], [n for n in names if len(n) == 2]

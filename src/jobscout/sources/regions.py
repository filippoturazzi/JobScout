"""Countries and areas, shared by the sources and the candidate filter.

A user writes "Brasil", a board writes "Brazil" or "BR", and all three must mean one country to
both the search and the filter. The table also has to know countries nobody searches in: the
filter can only tell that a posting is limited to India if it knows India is a country.

A country's identifier is its lower-case English name, except "usa" and "uk". Those match
JobSpy's ``Country`` values, which ``indeed`` sends as they are. The names are folded
(``text.fold``).
"""

import re
from functools import lru_cache

from jobscout.sources.text import fold

_CONTINENTS: dict[str, tuple[str, ...]] = {
    "europe": (
        "albania",
        "andorra",
        "austria",
        "belarus",
        "belgium",
        "bosnia and herzegovina",
        "bulgaria",
        "croatia",
        "cyprus",
        "czech republic",
        "denmark",
        "estonia",
        "finland",
        "france",
        "germany",
        "greece",
        "hungary",
        "iceland",
        "ireland",
        "italy",
        "kosovo",
        "latvia",
        "liechtenstein",
        "lithuania",
        "luxembourg",
        "malta",
        "moldova",
        "monaco",
        "montenegro",
        "netherlands",
        "north macedonia",
        "norway",
        "poland",
        "portugal",
        "romania",
        "serbia",
        "slovakia",
        "slovenia",
        "spain",
        "sweden",
        "switzerland",
        "ukraine",
        "uk",
    ),
    "north_america": ("canada", "usa"),
    "latin_america": (
        "argentina",
        "belize",
        "bolivia",
        "brazil",
        "chile",
        "colombia",
        "costa rica",
        "cuba",
        "dominican republic",
        "ecuador",
        "el salvador",
        "guatemala",
        "haiti",
        "honduras",
        "jamaica",
        "mexico",
        "nicaragua",
        "panama",
        "paraguay",
        "peru",
        "puerto rico",
        "uruguay",
        "venezuela",
    ),
    "asia": (
        "afghanistan",
        "armenia",
        "azerbaijan",
        "bangladesh",
        "cambodia",
        "china",
        "hong kong",
        "india",
        "indonesia",
        "japan",
        "kazakhstan",
        "kyrgyzstan",
        "laos",
        "malaysia",
        "mongolia",
        "myanmar",
        "nepal",
        "pakistan",
        "philippines",
        "singapore",
        "south korea",
        "sri lanka",
        "taiwan",
        "tajikistan",
        "thailand",
        "uzbekistan",
        "vietnam",
    ),
    "oceania": ("australia", "fiji", "new zealand", "papua new guinea"),
    "middle_east": (
        "bahrain",
        "iraq",
        "iran",
        "israel",
        "jordan",
        "kuwait",
        "lebanon",
        "oman",
        "qatar",
        "saudi arabia",
        "turkey",
        "united arab emirates",
    ),
    "africa": (
        "algeria",
        "angola",
        "botswana",
        "cameroon",
        "egypt",
        "ethiopia",
        "ghana",
        "ivory coast",
        "kenya",
        "madagascar",
        "mauritius",
        "morocco",
        "mozambique",
        "namibia",
        "nigeria",
        "rwanda",
        "senegal",
        "south africa",
        "tanzania",
        "tunisia",
        "uganda",
        "zambia",
        "zimbabwe",
    ),
}
# "Georgia" is deliberately absent. In a job location it nearly always means the US state, and
# reading "Atlanta, Georgia" as a foreign country would hide a posting without evidence.

_ALIASES: dict[str, tuple[str, ...]] = {
    "brazil": ("brasil", "br"),
    "portugal": ("pt",),
    "spain": ("espana", "es"),
    "usa": ("us", "united states", "united states of america", "estados unidos", "eua"),
    "uk": ("gb", "united kingdom", "great britain", "reino unido"),
    "germany": ("deutschland", "alemanha", "alemania", "de"),
    "france": ("franca", "francia"),
    "italy": ("italia",),
    "netherlands": ("holanda", "holland", "paises baixos", "the netherlands"),
    "belgium": ("belgica",),
    "switzerland": ("suica", "suiza"),
    "austria": ("osterreich",),
    "ireland": ("irlanda",),
    "poland": ("polonia",),
    "sweden": ("suecia",),
    "norway": ("noruega",),
    "denmark": ("dinamarca",),
    "finland": ("finlandia",),
    "greece": ("grecia",),
    "czech republic": ("czechia", "republica tcheca"),
    "romania": ("romenia",),
    "hungary": ("hungria",),
    "ukraine": ("ucrania",),
    "mexico": ("mejico",),
    "japan": ("japao", "japon"),
    "south korea": ("korea", "coreia do sul", "corea del sur"),
    "singapore": ("singapura", "singapur"),
    "philippines": ("filipinas",),
    "new zealand": ("nova zelandia", "nueva zelanda"),
    "south africa": ("africa do sul", "sudafrica"),
    "egypt": ("egito", "egipto"),
    "morocco": ("marrocos", "marruecos"),
    "saudi arabia": ("arabia saudita",),
    "united arab emirates": ("uae", "emirados arabes", "emirados arabes unidos"),
    "turkey": ("turkiye", "turquia"),
}
# The two-letter entries are ISO 3166-1 alpha-2 codes, only for the markets people search most.
# "ca" is deliberately absent: a user typing it is as likely to mean California, and a quiet
# search of the wrong market is worse than none. Spelling "Canada" out works.

_ENGLISH = {"usa": "United States", "uk": "United Kingdom"}

_SMALL_WORDS = {"and", "of"}

_AREAS: dict[str, tuple[str, ...]] = {
    "europe": ("europe",),
    "europa": ("europe",),
    "emea": ("europe", "middle_east", "africa"),
    "north america": ("north_america",),
    "america do norte": ("north_america",),
    "americas": ("north_america", "latin_america"),
    "latam": ("latin_america",),
    "latin america": ("latin_america",),
    "south america": ("latin_america",),
    "central america": ("latin_america",),
    "america latina": ("latin_america",),
    "america do sul": ("latin_america",),
    "apac": ("asia", "oceania"),
    "asia": ("asia",),
    "oceania": ("oceania",),
    "middle east": ("middle_east",),
    "mena": ("middle_east", "africa"),
    "africa": ("africa",),
}

_COUNTRIES: dict[str, str] = {
    **{country: country for group in _CONTINENTS.values() for country in group},
    **{alias: country for country, aliases in _ALIASES.items() for alias in aliases},
}

_AREA_COUNTRIES: dict[str, frozenset[str]] = {
    area: frozenset(country for continent in continents for country in _CONTINENTS[continent])
    # Mexico is in Latin America for the table and in North America for the job boards.
    | ({"mexico"} if area == "north america" else set())
    for area, continents in _AREAS.items()
}

_WORD_RE = re.compile(r"[^\W_]+")


def country_of(region: str) -> str | None:
    """The country a region names, or ``None`` when it names none this table knows."""
    return _COUNTRIES.get(fold(region))


def english_name(country: str) -> str:
    """``country`` the way an English-language site writes it."""
    if country in _ENGLISH:
        return _ENGLISH[country]
    return " ".join(word if word in _SMALL_WORDS else word.capitalize() for word in country.split())


def is_area(name: str) -> bool:
    """True when ``name`` is an area such as "Europe" or "LATAM", not a country."""
    return fold(name) in _AREAS


@lru_cache(maxsize=4096)
def countries_in(location: str) -> frozenset[str]:
    """Every country a location names, directly or through an area such as "Europe".

    The whole location is searched, not one comma-separated part at a time: boards order the
    parts differently ("São Paulo, SP, Brazil", "Remoto, Brazil", "Greater Curitiba"), so no
    one part is reliably the country. Whole words keep "India" out of "Indiana". A two-letter
    code only counts as the last part: "de" is Germany's and a word in "Rio de Janeiro".
    """
    padded = f" {' '.join(_WORD_RE.findall(fold(location)))} "
    named = {
        country for name, country in _COUNTRIES.items() if len(name) > 2 and f" {name} " in padded
    }
    code = _COUNTRIES.get(fold(location.rsplit(",", 1)[-1]))
    if code is not None:
        named.add(code)
    for area, countries in _AREA_COUNTRIES.items():
        if f" {area} " in padded:
            named |= countries
    return frozenset(named)

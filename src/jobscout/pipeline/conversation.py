"""The search conversation, as pure logic: no database, no LLM.

Everything the page shows while a search is being set up is computed here from a
``Conversation``: which question comes next, its options, the summary, and the preferences
"Search jobs" saves. The reading (``matching.terms.ExtractedProfile``) only suggests; a field's
*effective* value is the user's answer when there is one, else what the reading states. A
clicked answer always wins: a new reading never clears one.

Every function returns a new ``Conversation`` and leaves its input untouched.
"""

from typing import Literal

from pydantic import BaseModel

from jobscout.matching.terms import ExtractedProfile, profile_hash
from jobscout.models import UserPreferences
from jobscout.sources.regions import country_of, english_name, is_area

QuestionId = Literal["role", "level", "work_modes", "location", "country", "city", "skills"]

QUESTION_ORDER: tuple[QuestionId, ...] = (
    "role",
    "level",
    "work_modes",
    "location",
    "country",
    "city",
    "skills",
)
QUESTION_NUMBER: dict[QuestionId, int] = {
    "role": 1,
    "level": 2,
    "work_modes": 3,
    "location": 4,
    "country": 4,
    "city": 4,
    "skills": 5,
}
LEVELS = ("intern", "junior", "mid", "senior", "any")
WORK_MODES = ("remote", "hybrid", "onsite")
JUNIOR_EXCLUSIONS = ("senior", "sr", "lead", "staff", "principal")
_JUNIOR_LEVELS = {"intern", "junior"}
_UPPER_WORDS = {"ai", "ml", "llm", "qa", "ui", "ux", "bi", "sre", "nlp"}
_TITLE_WORDS = 6
_TITLE_LENGTH = 60


class InvalidAnswerError(ValueError):
    """An answer the question does not accept."""


class QuestionsPendingError(RuntimeError):
    """Preferences were asked for while questions are still unanswered."""


class Answer(BaseModel):
    choice: str
    values: list[str] = []


class Conversation(BaseModel):
    paragraph: str
    refinements: list[str] = []
    reading: ExtractedProfile | None = None
    reading_error: str | None = None
    answers: dict[QuestionId, Answer] = {}
    asked: list[QuestionId] = []  # order first answered, for the transcript
    confirmed: bool = False  # True after "Search jobs"; any change sets it False


class Option(BaseModel):
    choice: str
    value: str | None = None


class Question(BaseModel):
    id: QuestionId
    number: int
    position: int
    total: int
    multi: bool
    typed: bool
    options: list[Option]


class Summary(BaseModel):
    role: str | None
    terms: list[str]
    level: str | None
    work_modes: list[str]
    country: str | None
    city: str | None
    abroad_from: str | None
    skills: list[str]


# --- Building conversations -------------------------------------------------------------


def full_text(c: Conversation) -> str:
    """The paragraph and every refinement, separated by a blank line."""
    return "\n\n".join([c.paragraph, *c.refinements])


def with_reading(c: Conversation, reading: ExtractedProfile) -> Conversation:
    return c.model_copy(
        update={
            "reading": reading.model_copy(deep=True),
            "reading_error": None,
            "confirmed": False,
        },
        deep=True,
    )


def with_reading_error(c: Conversation, message: str) -> Conversation:
    return c.model_copy(update={"reading_error": message}, deep=True)


def with_refinement(c: Conversation, text: str) -> Conversation:
    return c.model_copy(
        update={"refinements": [*c.refinements, text], "confirmed": False}, deep=True
    )


# --- Effective values -------------------------------------------------------------------


def _country(region: str) -> str | None:
    """The English name of the country ``region`` names, or ``None``."""
    country = country_of(region)
    return english_name(country) if country is not None else None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value.lower() not in seen:
            seen.add(value.lower())
            result.append(value)
    return result


def _stated_regions(c: Conversation) -> list[str]:
    """The stated regions, with "City, Country" split into the city and the country.

    Models asked for a city's country often give both in one entry ("Brasilia, Brazil").
    Only a trailing country is split off, so "São Paulo, SP" stays one city.
    """
    if c.reading is None:
        return []
    regions: list[str] = []
    for region in c.reading.stated_regions:
        place, _, last = region.rpartition(",")
        if place.strip() and country_of(last) is not None:
            regions.extend([place.strip(), last.strip()])
        else:
            regions.append(region)
    return regions


def _stated_countries(c: Conversation) -> list[str]:
    return _dedupe([n for n in (_country(r) for r in _stated_regions(c)) if n is not None])


def _stated_city(c: Conversation) -> str | None:
    """The first stated region that is neither a country nor an area such as "Europe"."""
    for region in _stated_regions(c):
        if country_of(region) is None and not is_area(region):
            return region
    return None


def _level(c: Conversation) -> str | None:
    if "level" in c.answers:
        return c.answers["level"].choice
    if c.reading is not None and c.reading.seniority:
        return c.reading.seniority[0]
    return None


def _modes(c: Conversation) -> list[str]:
    if "work_modes" in c.answers:
        a = c.answers["work_modes"]
        return [] if a.choice == "any" else list(a.values)
    return list(c.reading.stated_work_modes) if c.reading is not None else []


def _remote_only(c: Conversation) -> bool:
    return set(_modes(c)) == {"remote"}


def _home(c: Conversation) -> str | None:
    """The country the user lives in or named: an answered country, else the first stated."""
    for qid in ("location", "country"):
        a = c.answers.get(qid)
        if a is not None and a.choice in ("country", "abroad") and a.values:
            return a.values[0]
    stated = _stated_countries(c)
    return stated[0] if stated else None


def _country_known(c: Conversation) -> str | None:
    """The country a hybrid or on-site search is in, ``None`` for anywhere or unknown."""
    a = c.answers.get("country")
    if a is not None:
        return a.values[0] if a.choice == "country" else None
    return _home(c)


def _applicable_stated_city(c: Conversation) -> str | None:
    """The stated city, unless the user answered a country the reading does not state.

    A reading with a city and no country at all is the user being asked the city's country:
    their answer completes the city rather than replacing it.
    """
    city = _stated_city(c)
    if city is None:
        return None
    answered = any(
        a.choice == "country" for qid, a in c.answers.items() if qid in ("location", "country")
    )
    stated = _stated_countries(c)
    if not answered or not stated or _country_known(c) in stated:
        return city
    return None


def _skills(c: Conversation) -> list[str]:
    if "skills" in c.answers:
        return list(c.answers["skills"].values)
    return list(c.reading.required_skills) if c.reading is not None else []


# --- Questions --------------------------------------------------------------------------


def _is_pending(c: Conversation, qid: QuestionId) -> bool:
    r = c.reading
    assert r is not None and r.terms
    if qid in c.answers:
        return False
    match qid:
        case "level":
            return not r.seniority
        case "work_modes":
            return not r.stated_work_modes
        case "location":
            return _remote_only(c) and not _stated_countries(c)
        case "country":
            return not _remote_only(c) and _country_known(c) is None
        case "city":
            return (
                not _remote_only(c)
                and _country_known(c) is not None
                and _applicable_stated_city(c) is None
            )
        case "skills":
            return not r.required_skills and bool(r.suggested_skills)
    return False


def pending(c: Conversation) -> list[QuestionId]:
    """The questions still to ask, in order."""
    if c.reading is None or not c.reading.terms:
        return ["role"]
    return [qid for qid in QUESTION_ORDER if qid != "role" and _is_pending(c, qid)]


def _options(c: Conversation, qid: QuestionId) -> list[Option]:
    match qid:
        case "level":
            return [Option(choice=level) for level in LEVELS]
        case "work_modes":
            return [Option(choice=mode) for mode in (*WORK_MODES, "any")]
        case "location":
            home = _home(c)
            options = [Option(choice="anywhere")]
            if home is not None:
                options = [
                    Option(choice="country", value=home),
                    *options,
                    Option(choice="abroad", value=home),
                ]
            return [*options, Option(choice="other")]
        case "country":
            return [Option(choice="anywhere"), Option(choice="other")]
        case "city":
            return [Option(choice="anywhere", value=_country_known(c)), Option(choice="other")]
        case "skills":
            suggested = c.reading.suggested_skills if c.reading is not None else []
            return [Option(choice="skill", value=skill) for skill in suggested]
    return []


def question_for(c: Conversation, qid: QuestionId) -> Question:
    """``qid`` as the page shows it, also when reopened from the summary."""
    numbers = list(dict.fromkeys(QUESTION_NUMBER[q] for q in [*c.asked, *pending(c)]))
    number = QUESTION_NUMBER[qid]
    if number not in numbers:
        numbers.append(number)
    return Question(
        id=qid,
        number=number,
        position=numbers.index(number) + 1,
        total=len(numbers),
        multi=qid in ("work_modes", "skills"),
        typed=qid in ("role", "location", "country", "city"),
        options=_options(c, qid),
    )


def current_question(c: Conversation) -> Question | None:
    todo = pending(c)
    return question_for(c, todo[0]) if todo else None


# --- Answers ----------------------------------------------------------------------------


def _one_country(a: Answer) -> Answer:
    if len(a.values) != 1:
        raise InvalidAnswerError("Name exactly one country.")
    name = _country(a.values[0])
    if name is None:
        raise InvalidAnswerError(f"Unknown country: {a.values[0]!r}.")
    return Answer(choice="country", values=[name])


def _validated(c: Conversation, qid: QuestionId, a: Answer) -> Answer:
    match qid:
        case "level":
            if a.choice in LEVELS:
                return Answer(choice=a.choice)
        case "work_modes":
            if a.choice == "any":
                return Answer(choice="any")
            if a.choice == "pick" and a.values and set(a.values) <= set(WORK_MODES):
                return Answer(choice="pick", values=list(dict.fromkeys(a.values)))
        case "location" | "country":
            if a.choice == "country":
                return _one_country(a)
            if a.choice == "anywhere":
                return Answer(choice="anywhere")
            if qid == "location" and a.choice == "abroad":
                home = _home(c)
                if home is None:
                    raise InvalidAnswerError("Abroad needs a home country.")
                return Answer(choice="abroad", values=[home])
        case "city":
            if a.choice == "anywhere":
                return Answer(choice="anywhere")
            if a.choice == "city" and len(a.values) == 1 and a.values[0].strip():
                return Answer(choice="city", values=[a.values[0].strip()])
        case "skills":
            if a.choice == "pick":
                return Answer(choice="pick", values=list(a.values))
    raise InvalidAnswerError(f"{qid!r} does not accept {a.choice!r}.")


def answer(c: Conversation, qid: QuestionId, a: Answer) -> Conversation:
    """Record ``a`` for ``qid``. Raises ``InvalidAnswerError`` for an answer it does not take.

    The role is never answered: typed text arrives as a refinement and is read again.
    """
    stored = _validated(c, qid, a)
    answers = {key: value.model_copy(deep=True) for key, value in c.answers.items()}
    answers[qid] = stored
    if qid in ("location", "country"):
        changed = c.model_copy(update={"answers": answers})
        if _home(changed) != _home(c) or _country_known(changed) != _country_known(c):
            answers.pop("city", None)
    asked = c.asked if qid in c.asked else [*c.asked, qid]
    return c.model_copy(
        update={"answers": answers, "asked": list(asked), "confirmed": False}, deep=True
    )


# --- What the conversation decided ------------------------------------------------------


def summary(c: Conversation) -> Summary:
    terms = list(c.reading.terms) if c.reading is not None else []
    country: str | None
    city: str | None = None
    abroad_from: str | None = None
    if _remote_only(c):
        a = c.answers.get("location")
        if a is None:
            stated = _stated_countries(c)
            country = stated[0] if stated else None
        elif a.choice == "country":
            country = a.values[0]
        else:
            country = None
            if a.choice == "abroad":
                abroad_from = a.values[0]
    else:
        country = _country_known(c)
        if country is not None:
            a = c.answers.get("city")
            if a is None:
                city = _applicable_stated_city(c)
            elif a.choice == "city":
                city = a.values[0]
        elif "country" not in c.answers:
            city = _stated_city(c)  # shown while the country question is still open
    return Summary(
        role=terms[0] if terms else None,
        terms=terms,
        level=_level(c),
        work_modes=_modes(c),
        country=country,
        city=city,
        abroad_from=abroad_from,
        skills=_skills(c),
    )


def to_preferences(c: Conversation) -> dict[str, object]:
    """The preference fields "Search jobs" saves. Raises while questions are pending."""
    if pending(c):
        raise QuestionsPendingError(f"Questions still pending: {', '.join(pending(c))}.")
    assert c.reading is not None
    s = summary(c)
    if "level" in c.answers:
        level = c.answers["level"].choice
        seniority = [] if level == "any" else [level]
    else:
        seniority = list(c.reading.seniority)
    excluded_keywords = list(c.reading.excluded_keywords)
    if s.level in _JUNIOR_LEVELS:
        excluded_keywords += JUNIOR_EXCLUSIONS
    regions: list[str]
    excluded_regions: list[str] = []
    if _remote_only(c) and "location" not in c.answers:
        regions = _stated_countries(c)
    else:
        regions = [s.country] if s.country is not None else []
        if s.abroad_from is not None:
            excluded_regions = [s.abroad_from]
    text = full_text(c)
    return {
        "profile_summary": text,
        "profile_hash": profile_hash(text),
        "search_terms": s.terms,
        "titles": [],  # the role lives in the terms; a stored title filter would hide jobs
        "seniority": seniority,
        "excluded_keywords": _dedupe(excluded_keywords),
        "work_modes": s.work_modes,
        "regions": regions,
        "excluded_regions": excluded_regions,
        "city": s.city,
        "required_skills": s.skills,
    }


def widenings(c: Conversation) -> list[tuple[str, QuestionId, Answer]]:
    """One-answer changes that widen the search, each only when it changes something."""
    result: list[tuple[str, QuestionId, Answer]] = []
    modes = _modes(c)
    for mode in ("remote", "hybrid"):
        if modes and mode not in modes:
            result.append(
                (f"include_{mode}", "work_modes", Answer(choice="pick", values=[*modes, mode]))
            )
    s = summary(c)
    if s.city is not None and s.country is not None:
        result.append(("whole_country", "city", Answer(choice="anywhere")))
    level = _level(c)
    if level is not None and level != "any":
        result.append(("any_level", "level", Answer(choice="any")))
    return result


def _capitalise(word: str) -> str:
    return word.upper() if word.lower() in _UPPER_WORDS else word.capitalize()


def title(c: Conversation) -> str:
    """Level and role ("Junior AI Engineer"); with no role, the paragraph's first words."""
    terms = c.reading.terms if c.reading is not None else []
    if not terms:
        return " ".join(c.paragraph.split()[:_TITLE_WORDS])[:_TITLE_LENGTH]
    level = _level(c)
    words = ([level] if level is not None and level != "any" else []) + terms[0].split()
    return " ".join(_capitalise(word) for word in words)


def from_preferences(prefs: UserPreferences) -> Conversation:
    """The conversation that saved ``prefs``, rebuilt for the summary.

    Only a field with a stored value becomes an answer: an empty one is left open, so a later
    reading can fill it, or its question is asked again. A region that names no country (a
    city, an area such as "Europe") is kept as stated by the reading rather than read as
    "anywhere". Stored ``titles`` lead the terms; the conversation saves them as terms only.
    The result is confirmed only when no question is pending.
    """
    answers: dict[QuestionId, Answer] = {}
    reading_seniority: list[str] = []
    junior = bool(prefs.seniority) and prefs.seniority[0] in _JUNIOR_LEVELS
    stated_regions: list[str] = []
    if prefs.seniority and prefs.seniority[0] in LEVELS:
        answers["level"] = Answer(choice=prefs.seniority[0])
    elif prefs.seniority:
        reading_seniority = list(prefs.seniority)
    if prefs.work_modes:
        answers["work_modes"] = Answer(choice="pick", values=list(prefs.work_modes))
    countries = [n for n in (_country(r) for r in prefs.regions) if n is not None]
    unresolved = len(countries) < len(prefs.regions)
    if set(prefs.work_modes) == {"remote"}:
        if unresolved:
            stated_regions = list(prefs.regions)
        elif len(countries) > 1:
            stated_regions = countries
        elif countries:
            answers["location"] = Answer(choice="country", values=countries)
        elif prefs.excluded_regions and _country(prefs.excluded_regions[0]) is not None:
            answers["location"] = Answer(
                choice="abroad", values=[str(_country(prefs.excluded_regions[0]))]
            )
    else:
        if unresolved:
            stated_regions = list(prefs.regions)
        elif countries:
            answers["country"] = Answer(choice="country", values=countries[:1])
        if prefs.city and countries:
            answers["city"] = Answer(choice="city", values=[prefs.city])
        elif prefs.city and prefs.city not in stated_regions:
            stated_regions.append(prefs.city)
    if prefs.required_skills:
        answers["skills"] = Answer(choice="pick", values=list(prefs.required_skills))
    reading = ExtractedProfile(
        terms=_dedupe([*prefs.titles, *prefs.search_terms]),
        seniority=reading_seniority,
        # The junior exclusions were added by the level; they return only with that level.
        excluded_keywords=[
            word
            for word in prefs.excluded_keywords
            if not (junior and word.lower() in JUNIOR_EXCLUSIONS)
        ],
        stated_regions=stated_regions,
    )
    rebuilt = Conversation(
        paragraph=prefs.profile_summary,
        reading=reading,
        answers=answers,
        asked=[qid for qid in QUESTION_ORDER if qid in answers],
    )
    return rebuilt.model_copy(update={"confirmed": not pending(rebuilt)})

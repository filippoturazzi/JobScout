"""Turn the user's free-text paragraph into search terms and structured preferences.

The job APIs match keywords, so ``terms`` must be short. The same call also fills the
fields the deterministic filter (``pipeline.filters``) and the LLM prompt
(``matching.prompts``) read, otherwise a paragraph-only profile leaves them empty and both
silently stop constraining anything.
"""

import hashlib
from typing import cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

MAX_TERM_WORDS = 3
MAX_TERMS = 8

# The only values pipeline.filters._passes_work_mode understands, lowercase.
WORK_MODES = ("remote", "hybrid", "onsite")
_WORK_MODE_ALIASES = {"on-site": "onsite", "on site": "onsite", "in-office": "onsite"}

SYSTEM_PROMPT = f"""You read a candidate's description of the job they want and extract search
terms and structured preferences from it.

Rules:
- terms: job-board search keywords, MOST IMPORTANT FIRST, at most {MAX_TERMS}. Each term is one to
  {MAX_TERM_WORDS} words (a role or a core technology, e.g. "ai engineer", "python"). Never a
  sentence: the job APIs match keywords and a long query returns nothing.
- titles: job titles the candidate would accept, short (e.g. "AI Engineer"). A posting is only
  kept if its title contains every word of one of these, so keep them to the core role words.
- seniority: e.g. junior, mid, senior.
- work_modes: only from {", ".join(WORK_MODES)}. Leave empty if the text does not say.
- regions: countries or cities the candidate would work in, as they appear in job locations.
- required_skills: skills the candidate insists on.
- excluded_keywords: words that must NOT appear in a job title (e.g. "senior" for a junior).
- Use only what the text states. Leave a field empty rather than guess."""


class ExtractedProfile(BaseModel):
    """What the LLM must return for one profile paragraph."""

    terms: list[str] = Field(
        default_factory=list,
        description=f"Search keywords, most important first, 1-{MAX_TERM_WORDS} words each.",
    )
    titles: list[str] = Field(default_factory=list, description="Acceptable job titles.")
    seniority: list[str] = Field(default_factory=list, description="Seniority levels.")
    work_modes: list[str] = Field(
        default_factory=list, description=f"Subset of: {', '.join(WORK_MODES)}."
    )
    regions: list[str] = Field(default_factory=list, description="Acceptable countries/cities.")
    required_skills: list[str] = Field(default_factory=list, description="Must-have skills.")
    excluded_keywords: list[str] = Field(
        default_factory=list, description="Words to reject in a job title."
    )


def profile_hash(paragraph: str) -> str:
    """Stable fingerprint of the paragraph's words; whitespace changes do not alter it."""
    normalized = " ".join(paragraph.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(value.split())
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            result.append(cleaned)
    return result


def _clean_work_modes(values: list[str]) -> list[str]:
    modes: list[str] = []
    for value in values:
        mode = value.strip().lower()
        mode = _WORK_MODE_ALIASES.get(mode, mode)
        if mode in WORK_MODES and mode not in modes:
            modes.append(mode)
    return modes


def extract_profile(paragraph: str, llm: BaseChatModel) -> ExtractedProfile:
    """Extract terms and preferences. Raises ``ValueError`` if there is nothing to search for."""
    if not paragraph.strip():
        raise ValueError("The profile paragraph is empty; there is nothing to search for.")
    structured = llm.with_structured_output(ExtractedProfile)
    # Typed loosely because it also accepts dict/JSON schemas; a pydantic class yields an
    # instance of that class (same pattern as matching.graph).
    raw = cast(
        ExtractedProfile,
        structured.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=paragraph)]),
    )
    terms = [term for term in _dedupe(raw.terms) if len(term.split()) <= MAX_TERM_WORDS]
    terms = terms[:MAX_TERMS]
    if not terms:
        raise ValueError("No usable search terms could be extracted from the profile paragraph.")
    return ExtractedProfile(
        terms=terms,
        titles=_dedupe(raw.titles),
        seniority=[value.lower() for value in _dedupe(raw.seniority)],
        work_modes=_clean_work_modes(raw.work_modes),
        regions=_dedupe(raw.regions),
        required_skills=_dedupe(raw.required_skills),
        excluded_keywords=_dedupe(raw.excluded_keywords),
    )

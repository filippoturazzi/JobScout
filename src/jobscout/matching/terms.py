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
MAX_SUGGESTED_SKILLS = 8

SYSTEM_PROMPT = f"""You read a candidate's description of the job they want and extract search
terms and structured preferences from it.

Rules:
- terms: job-board search keywords, MOST IMPORTANT FIRST, at most {MAX_TERMS}. Each term is one to
  {MAX_TERM_WORDS} words (a role or a core technology, e.g. "ai engineer", "python"). Never a
  sentence: the job APIs match keywords and a long query returns nothing.
- seniority: e.g. junior, mid, senior.
- required_skills: skills the candidate insists on.
- suggested_skills: up to {MAX_SUGGESTED_SKILLS} skills typical for this role, whether or not the
  text names them. They are options to choose from, not requirements.
- excluded_keywords: words that must NOT appear in a job title (e.g. "senior" for a junior).
- stated_work_modes: the work modes the text says it wants: remote, hybrid or onsite.
- stated_regions: the countries or cities the text says it wants to work in.
- Use only what the text states for every field except suggested_skills. Leave a field empty
  rather than guess."""


class _LLMOutput(BaseModel):
    """The only fields the LLM is asked for; suppressed ones never reach its schema."""

    terms: list[str] = Field(
        default_factory=list,
        description=f"Search keywords, most important first, 1-{MAX_TERM_WORDS} words each.",
    )
    seniority: list[str] = Field(default_factory=list, description="Seniority levels.")
    required_skills: list[str] = Field(default_factory=list, description="Must-have skills.")
    suggested_skills: list[str] = Field(
        default_factory=list,
        description=(
            "Skills typical for the role the text describes, for the candidate to pick from."
        ),
    )
    excluded_keywords: list[str] = Field(
        default_factory=list, description="Words to reject in a job title."
    )
    stated_work_modes: list[str] = Field(
        default_factory=list, description="Work modes the text states: remote, hybrid, onsite."
    )
    stated_regions: list[str] = Field(
        default_factory=list, description="Countries or cities the text states."
    )


class ExtractedProfile(_LLMOutput):
    """The extraction result, shaped like the preference columns it feeds.

    ``titles``, ``regions`` and ``work_modes`` are part of the shape for downstream
    consumers but are deliberately never filled, and the LLM is not asked for them. Rule:
    automatic extraction may add exclusions, never restrictions. Each is a hard gate that
    can hide the best match without a trace: ``pipeline.filters._passes_titles`` needs EVERY
    word of a title in the job title ("AI Engineer" drops "Machine Learning Engineer");
    ``_passes_region`` drops non-remote jobs whose location lacks the region ("Brazil" never
    matches "Sao Paulo, SP"); ``_passes_work_mode`` drops on-site jobs once "remote" is set.
    The search terms already decided what was fetched, ranking by score is the filter, and
    the paragraph itself (``profile_summary``) reaches the match prompt verbatim. Do not
    "fix" the empty fields.

    ``stated_work_modes`` and ``stated_regions`` are how a paragraph's "remote" still counts:
    nothing filters on them. They are what the conversation shows already selected, and only
    the user's confirmation turns them into ``work_modes`` and ``regions``.
    """

    titles: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    work_modes: list[str] = Field(default_factory=list)


def profile_hash(paragraph: str) -> str:
    """Stable fingerprint of the paragraph's words; whitespace changes do not alter it."""
    normalized = " ".join(paragraph.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


_WORK_MODES = {
    "remote": "remote",
    "remoto": "remote",
    "hybrid": "hybrid",
    "hibrido": "hybrid",
    "híbrido": "hybrid",
    "onsite": "onsite",
    "on-site": "onsite",
    "on site": "onsite",
    "presencial": "onsite",
}


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(value.split())
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            result.append(cleaned)
    return result


def read_profile(paragraph: str, llm: BaseChatModel) -> ExtractedProfile:
    """Read the paragraph once. Raises ``ValueError`` only if the paragraph is blank.

    ``terms`` may come back empty when the LLM found nothing usable; the caller decides
    whether that is an error.
    """
    if not paragraph.strip():
        raise ValueError("The profile paragraph is empty; there is nothing to search for.")
    structured = llm.with_structured_output(_LLMOutput)
    # Typed loosely because it also accepts dict/JSON schemas; a pydantic class yields an
    # instance of that class (same pattern as matching.graph).
    raw = cast(
        _LLMOutput,
        structured.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=paragraph)]),
    )
    terms = [term for term in _dedupe(raw.terms) if len(term.split()) <= MAX_TERM_WORDS]
    terms = terms[:MAX_TERMS]
    required_skills = _dedupe(raw.required_skills)
    required_lower = {skill.lower() for skill in required_skills}
    suggested_skills = [
        skill for skill in _dedupe(raw.suggested_skills) if skill.lower() not in required_lower
    ]
    return ExtractedProfile(
        terms=terms,
        seniority=[value.lower() for value in _dedupe(raw.seniority)],
        required_skills=required_skills,
        suggested_skills=suggested_skills[:MAX_SUGGESTED_SKILLS],
        excluded_keywords=_dedupe(raw.excluded_keywords),
        stated_work_modes=_dedupe(
            [
                _WORK_MODES[mode.strip().lower()]
                for mode in raw.stated_work_modes
                if mode.strip().lower() in _WORK_MODES
            ]
        ),
        stated_regions=_dedupe(raw.stated_regions),
    )


def extract_profile(paragraph: str, llm: BaseChatModel) -> ExtractedProfile:
    """Extract terms and preferences. Raises ``ValueError`` if there is nothing to search for."""
    profile = read_profile(paragraph, llm)
    if not profile.terms:
        raise ValueError("No usable search terms could be extracted from the profile paragraph.")
    return profile

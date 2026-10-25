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

SYSTEM_PROMPT = f"""You read a candidate's description of the job they want and extract search
terms and structured preferences from it.

Rules:
- terms: job-board search keywords, MOST IMPORTANT FIRST, at most {MAX_TERMS}. Each term is one to
  {MAX_TERM_WORDS} words (a role or a core technology, e.g. "ai engineer", "python"). Never a
  sentence: the job APIs match keywords and a long query returns nothing.
- seniority: e.g. junior, mid, senior.
- required_skills: skills the candidate insists on.
- excluded_keywords: words that must NOT appear in a job title (e.g. "senior" for a junior).
- Use only what the text states. Leave a field empty rather than guess."""


class _LLMOutput(BaseModel):
    """The only fields the LLM is asked for; suppressed ones never reach its schema."""

    terms: list[str] = Field(
        default_factory=list,
        description=f"Search keywords, most important first, 1-{MAX_TERM_WORDS} words each.",
    )
    seniority: list[str] = Field(default_factory=list, description="Seniority levels.")
    required_skills: list[str] = Field(default_factory=list, description="Must-have skills.")
    excluded_keywords: list[str] = Field(
        default_factory=list, description="Words to reject in a job title."
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
    """

    titles: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    work_modes: list[str] = Field(default_factory=list)


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


def extract_profile(paragraph: str, llm: BaseChatModel) -> ExtractedProfile:
    """Extract terms and preferences. Raises ``ValueError`` if there is nothing to search for."""
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
    if not terms:
        raise ValueError("No usable search terms could be extracted from the profile paragraph.")
    return ExtractedProfile(
        terms=terms,
        seniority=[value.lower() for value in _dedupe(raw.seniority)],
        required_skills=_dedupe(raw.required_skills),
        excluded_keywords=_dedupe(raw.excluded_keywords),
    )

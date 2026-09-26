"""The LLM's structured output and the graph's state."""

from typing import TypedDict

from pydantic import BaseModel, Field


class EvaluationResult(BaseModel):
    """What the LLM must return for one (job, profile) pair."""

    score: int = Field(ge=0, le=100, description="Fit from 0 (irrelevant) to 100 (ideal).")
    reasoning: str = Field(description="Two or three sentences justifying the score.")
    matched_skills: list[str] = Field(
        default_factory=list, description="Skills required by the job that the profile has."
    )
    missing_skills: list[str] = Field(
        default_factory=list, description="Skills required by the job that the profile lacks."
    )
    red_flags: list[str] = Field(
        default_factory=list,
        description="Concrete mismatches: seniority, location, salary, contract type.",
    )


class MatchState(TypedDict, total=False):
    """State threaded through the matching graph, one run per (job, user)."""

    job_id: int
    user_id: int
    job_text: str
    prompt: str
    profile_text: str
    job_embedding: list[float]
    profile_embedding: list[float]
    similarity: float
    min_score: int
    evaluation: EvaluationResult | None
    llm_model: str | None
    should_notify: bool

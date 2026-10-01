from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jobscout.models.user import non_nullable_preference_fields

WorkMode = Literal["remote", "hybrid", "onsite"]


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    external_id: str
    title: str
    company: str
    location: str | None
    remote: bool
    url: str
    description: str
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    tags: list[str]
    posted_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool


class PreferencesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    titles: list[str]
    seniority: list[str]
    work_modes: list[str]
    regions: list[str]
    min_salary: int | None
    salary_currency: str | None
    required_skills: list[str]
    nice_to_have_skills: list[str]
    excluded_keywords: list[str]
    profile_summary: str
    min_score_to_notify: int
    updated_at: datetime


class PreferencesUpdate(BaseModel):
    """All fields optional; only the ones sent are changed."""

    model_config = ConfigDict(extra="forbid")

    titles: list[str] | None = None
    seniority: list[str] | None = None
    work_modes: list[WorkMode] | None = None
    regions: list[str] | None = None
    min_salary: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    required_skills: list[str] | None = None
    nice_to_have_skills: list[str] | None = None
    excluded_keywords: list[str] | None = None
    profile_summary: str | None = None
    min_score_to_notify: int | None = Field(default=None, ge=0, le=100)

    @field_validator(*sorted(non_nullable_preference_fields()), mode="before")
    @classmethod
    def _reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("field cannot be null")
        return value


class MatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    similarity: float
    score: int | None
    reasoning: str | None
    matched_skills: list[str]
    missing_skills: list[str]
    red_flags: list[str]
    status: str
    llm_model: str | None
    job: JobRead


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job: str
    started_at: datetime
    finished_at: datetime | None
    ok: bool
    error: str | None
    counters: dict[str, int]

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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

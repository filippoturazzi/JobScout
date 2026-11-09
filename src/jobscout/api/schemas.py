from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jobscout.pipeline.conversation import Answer, Question, QuestionId, Summary
from jobscout.sources.base import SourceStatus


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
    work_mode: Literal["remote", "hybrid", "onsite"] | None = None


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
    updated_at: datetime
    job: JobRead


class MatchStatusUpdate(BaseModel):
    status: Literal["saved", "dismissed", "applied"]


class SearchStarted(BaseModel):
    run_id: int


class RunSource(BaseModel):
    name: str
    state: Literal["waiting", "searching", "done", "failed", "skipped"]
    fetched: int
    queries_done: int
    queries_total: int
    detail: str | None
    # What the run could not do with this source without it failing: a country past the
    # search budget, a region the source could not map. Rows from before it read as none.
    notes: list[str] = Field(default_factory=list)


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job: str
    search_id: int | None
    started_at: datetime
    finished_at: datetime | None
    ok: bool
    error: str | None
    counters: dict[str, int]
    sources: list[RunSource]


class ReadingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    terms: list[str]
    seniority: list[str]
    required_skills: list[str]
    stated_work_modes: list[str]
    stated_regions: list[str]
    suggested_skills: list[str]


class WideningRead(BaseModel):
    id: str
    question: QuestionId
    answer: Answer


class SearchListItem(BaseModel):
    id: int
    title: str
    last_used_at: datetime
    running: bool


class SearchCreate(BaseModel):
    paragraph: str = Field(min_length=1)


class AnswerCreate(BaseModel):
    question: QuestionId
    choice: str
    values: list[str] = []


class RefinementCreate(BaseModel):
    text: str = Field(min_length=1)


class SearchRead(BaseModel):
    id: int
    title: str
    created_at: datetime
    last_used_at: datetime
    paragraph: str
    refinements: list[str]
    reading: ReadingRead | None
    reading_error: str | None
    asked: list[QuestionId]
    answers: dict[QuestionId, Answer]
    question: Question | None
    summary: Summary
    confirmed: bool
    widenings: list[WideningRead]
    latest_run: RunRead | None


class MatchList(BaseModel):
    matches: list[MatchRead]
    found: int
    waiting: int


class SearchTitle(BaseModel):
    id: int
    title: str


class MyJobRead(BaseModel):
    match: MatchRead
    searches: list[SearchTitle]


class MyJobsRead(BaseModel):
    items: list[MyJobRead]
    counts: dict[str, int]


class StatusRead(BaseModel):
    llm_key_found: bool
    llm_provider: str
    llm_model: str
    embedding_model: str
    sources: list[SourceStatus]
    running_search_id: int | None
    locale: str


class LocaleBody(BaseModel):
    locale: Literal["en", "pt-BR"]

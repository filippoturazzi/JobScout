from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from langchain_core.language_models import BaseChatModel
from sqlmodel import Session, col, desc, select

from jobscout.api.deps import get_chat_model, get_current_user_id, get_session
from jobscout.api.routers.jobs import read_job
from jobscout.api.routers.matches import read_match
from jobscout.api.schemas import (
    AnswerCreate,
    MatchList,
    ReadingRead,
    RefinementCreate,
    RunRead,
    SearchCreate,
    SearchListItem,
    SearchRead,
    SearchStarted,
    UnscoredRead,
    WideningRead,
)
from jobscout.config import get_settings
from jobscout.models import Run, Search
from jobscout.pipeline import conversation as conv
from jobscout.pipeline import searches as svc
from jobscout.pipeline.conversation import Answer, Question, QuestionId
from jobscout.pipeline.run import count_waiting, list_matches, list_unscored
from jobscout.scheduler import JobScoutScheduler, SearchBusyError

router = APIRouter(prefix="/searches", tags=["searches"])

DEFAULT_LISTING_LIMIT = 500


def _scheduler(request: Request) -> JobScoutScheduler:
    scheduler: JobScoutScheduler | None = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="no scheduler to run the search on")
    return scheduler


def _running(request: Request) -> tuple[int, int] | None:
    scheduler: JobScoutScheduler | None = getattr(request.app.state, "scheduler", None)
    return scheduler.running_search() if scheduler is not None else None


def _run_in_flight(scheduler: JobScoutScheduler, search_id: int) -> int | None:
    """The run id when this search is the one running; refuses when another one is.

    Checked before anything is written: confirming while this search runs would stale its
    matches and rewrite its preferences under the run in flight, which keeps the old ones.
    """
    running = scheduler.running_search()
    if running is None:
        return None
    if running[0] != search_id:
        raise SearchBusyError(running[0])
    return running[1]


def _read(session: Session, search: Search) -> SearchRead:
    assert search.id is not None
    c = svc.conversation_of(search)
    latest = session.exec(
        select(Run)
        .where(col(Run.search_id) == search.id)
        .order_by(desc(col(Run.started_at)), desc(col(Run.id)))
    ).first()
    return SearchRead(
        id=search.id,
        title=search.title,
        created_at=search.created_at,
        last_used_at=search.last_used_at,
        paragraph=c.paragraph,
        refinements=c.refinements,
        reading=ReadingRead.model_validate(c.reading) if c.reading is not None else None,
        reading_error=c.reading_error,
        asked=c.asked,
        answers=c.answers,
        question=conv.current_question(c),
        summary=conv.summary(c),
        confirmed=c.confirmed,
        widenings=[
            WideningRead(id=wid, question=question, answer=answer)
            for wid, question, answer in conv.widenings(c)
        ],
        latest_run=RunRead.model_validate(latest) if latest is not None else None,
    )


@router.get("", response_model=list[SearchListItem])
def read_searches(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> list[SearchListItem]:
    running = _running(request)
    return [
        SearchListItem(
            id=s.id,
            title=s.title,
            last_used_at=s.last_used_at,
            running=running is not None and running[0] == s.id,
        )
        for s in svc.list_searches(session, user_id)
        if s.id is not None
    ]


@router.post("", status_code=201, response_model=SearchRead)
def create_search(
    payload: SearchCreate,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
    chat: Annotated[BaseChatModel, Depends(get_chat_model)],
) -> SearchRead:
    """A new search from a paragraph, read once; the answer carries the first question."""
    try:
        search = svc.create_search(session, get_settings(), user_id, payload.paragraph, chat)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _read(session, search)


@router.get("/{search_id}", response_model=SearchRead)
def read_search(
    search_id: int,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> SearchRead:
    return _read(session, svc.get_search(session, user_id, search_id))


@router.delete("/{search_id}", status_code=204)
def delete_search(
    search_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> Response:
    svc.get_search(session, user_id, search_id)
    running = _running(request)
    if running is not None and running[0] == search_id:
        raise SearchBusyError(search_id)
    svc.delete_search(session, user_id, search_id)
    return Response(status_code=204)


@router.get("/{search_id}/questions/{question_id}", response_model=Question)
def read_question(
    search_id: int,
    question_id: QuestionId,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> Question:
    """One question with its options, for editing an answer from the summary."""
    c = svc.conversation_of(svc.get_search(session, user_id, search_id))
    return conv.question_for(c, question_id)


@router.post("/{search_id}/answers", response_model=SearchRead)
def answer_question(
    search_id: int,
    payload: AnswerCreate,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> SearchRead:
    search = svc.answer_question(
        session,
        user_id,
        search_id,
        payload.question,
        Answer(choice=payload.choice, values=payload.values),
    )
    return _read(session, search)


@router.post("/{search_id}/refinements", response_model=SearchRead)
def refine_search(
    search_id: int,
    payload: RefinementCreate,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
    chat: Annotated[BaseChatModel, Depends(get_chat_model)],
) -> SearchRead:
    """Add text and read it all again. Never runs the search."""
    return _read(session, svc.refine(session, user_id, search_id, payload.text, chat))


@router.post("/{search_id}/reread", response_model=SearchRead)
def reread_search(
    search_id: int,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
    chat: Annotated[BaseChatModel, Depends(get_chat_model)],
) -> SearchRead:
    return _read(session, svc.reread(session, user_id, search_id, chat))


@router.post("/{search_id}/run", status_code=202, response_model=SearchStarted)
def run_search(
    search_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> SearchStarted:
    """Confirm the conversation as the search's preferences, then fetch and score in the
    background. Poll ``GET /searches/{id}/runs/{run_id}`` for progress."""
    scheduler = _scheduler(request)
    svc.get_search(session, user_id, search_id)
    in_flight = _run_in_flight(scheduler, search_id)  # a refused start changes nothing
    if in_flight is not None:
        return SearchStarted(run_id=in_flight)
    svc.confirm(session, get_settings(), user_id, search_id)
    return SearchStarted(run_id=scheduler.start_search(search_id))


@router.post("/{search_id}/rank", status_code=202, response_model=SearchStarted)
def rank_search(
    search_id: int,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> SearchStarted:
    """Score what the search already holds, calling no source."""
    scheduler = _scheduler(request)
    svc.get_search(session, user_id, search_id)
    in_flight = _run_in_flight(scheduler, search_id)
    if in_flight is not None:
        return SearchStarted(run_id=in_flight)
    return SearchStarted(run_id=scheduler.start_search(search_id, fetch=False))


@router.get("/{search_id}/runs/{run_id}", response_model=RunRead)
def read_search_run(
    search_id: int,
    run_id: int,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
) -> RunRead:
    svc.get_search(session, user_id, search_id)
    run = session.get(Run, run_id)
    if run is None or run.search_id != search_id:
        raise HTTPException(status_code=404, detail=f"no run {run_id} for search {search_id}")
    return RunRead.model_validate(run)


@router.get("/{search_id}/matches", response_model=MatchList)
def read_search_matches(
    search_id: int,
    session: Annotated[Session, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
    min_score: Annotated[int, Query(ge=0, le=100)] = 0,
    status: Annotated[
        str | None,
        Query(
            description="Filter by match status; `low` reveals prefiltered, unscored rows, "
            "and `dismissed` or `applied` the ones the default listing hides."
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> MatchList:
    """This search's matches, best first, with how many the default listing holds and how
    many jobs still wait to be scored, and the jobs that have no score at all."""
    svc.get_search(session, user_id, search_id)
    rows = list_matches(session, search_id, min_score=min_score, status=status, limit=limit)
    found = len(list_matches(session, search_id, limit=DEFAULT_LISTING_LIMIT))
    return MatchList(
        matches=[read_match(match, job) for match, job in rows],
        found=found,
        waiting=count_waiting(session, search_id),
        unscored=[
            UnscoredRead(job=read_job(item.job), similarity=item.similarity, match_id=item.match_id)
            for item in list_unscored(session, search_id, limit=DEFAULT_LISTING_LIMIT)
        ],
    )

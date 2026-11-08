"""Build a demo database with searches in every state the page shows.

    uv run python scripts/seed_demo.py demo.db

No network and no LLM: jobs, matches and runs are written directly, and the searches go
through the same pipeline functions the app uses. Timestamps are relative to now, so
"2d ago" reads naturally whenever the database is made.
"""

# ruff: noqa: E501
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session

from jobscout.config import Settings
from jobscout.db import create_engine_from_url, init_db
from jobscout.matching.terms import ExtractedProfile
from jobscout.models import Job, Match, Run, Search
from jobscout.models.base import utcnow
from jobscout.pipeline import conversation as conv
from jobscout.pipeline.conversation import Answer, Conversation, QuestionId
from jobscout.pipeline.ingest import content_hash, fingerprint
from jobscout.pipeline.searches import add_search, confirm, record_fetched, save_conversation
from jobscout.pipeline.users import get_or_create_default_user

MODEL = "demo-model"
MIN = timedelta(minutes=1)
H = timedelta(hours=1)
D = timedelta(days=1)

# title, company, location, source, remote, work mode in the description, age, salary
JobSpec = tuple[str, str, str, str, bool, str, timedelta, tuple[int, int, str] | None]

BRL_6_8 = (6000, 8000, "BRL")
BRL_7_9 = (7000, 9000, "BRL")
USD_40_55 = (40000, 55000, "USD")

# fmt: off
SEARCH1_JOBS: list[tuple[JobSpec, int]] = [
    (("Junior AI Engineer", "Nuvia", "Remote, Brazil", "linkedin", True, "remote", 2 * D, None), 92),
    (("LLM Application Developer", "Orbe Labs", "São Paulo, SP", "indeed", False, "hybrid", 5 * H, BRL_6_8), 87),
    (("AI Engineer (Python)", "Kestra", "Worldwide", "himalayas", True, "remote", 1 * D, USD_40_55), 81),
    (("Machine Learning Engineer", "Tauá", "Remote, Brazil", "remotive", True, "remote", 3 * D, None), 74),
    (("Backend Python Developer", "Ponto Dados", "São Paulo, SP", "linkedin", False, "hybrid", 6 * D, None), 66),
    (("Prompt Engineer", "Vetor", "Remote, Brazil", "linkedin", True, "remote", 4 * D, None), 63),
    (("NLP Engineer", "Ágora", "Remote, Brazil", "remotive", True, "remote", 5 * D, None), 61),
    (("Python Developer (AI)", "Cascata", "São Paulo, SP", "indeed", False, "hybrid", 7 * D, BRL_6_8), 60),
    (("MLOps Engineer", "Fluxo", "Remote, Brazil", "himalayas", True, "remote", 8 * D, None), 58),
    (("Applied AI Engineer", "Lume", "Remote, Brazil", "linkedin", True, "remote", 9 * D, None), 57),
    (("Data Scientist", "Pixel Pay", "Remote, Brazil", "remotive", True, "remote", 10 * D, None), 56),
    (("AI Support Engineer", "Marola", "São Paulo, SP", "indeed", False, "hybrid", 11 * D, None), 55),
    # Applied for: the default listing hides it, so the search still shows 12.
    (("Junior ML Engineer", "Brasa", "Remote, Brazil", "linkedin", True, "remote", 12 * D, None), 54),
]
SHARED_TITLE = "AI Engineer (Python)"  # also in search 2, at a lower score
SHARED_SCORE_IN_SEARCH2 = 72

SEARCH1_WAITING: list[JobSpec] = [
    (f"AI Developer {i}", f"Waiting Co {i}", "Remote, Brazil", "linkedin", True, "remote", i * 5 * H, None)
    for i in range(1, 10)
]

SEARCH2_JOBS: list[tuple[JobSpec, int]] = [
    (("Python Backend Developer", "Lumen", "Remote, Brazil", "remotive", True, "remote", 4 * D, BRL_7_9), 77),
    (("Backend Engineer (Django)", "Sol Digital", "Remote, Brazil", "linkedin", True, "remote", 2 * D, None), 70),
    (("Python Developer", "Cais", "Remote, Brazil", "himalayas", True, "remote", 6 * D, None), 64),
    (("API Engineer", "Brisa Cloud", "Remote, Brazil", "linkedin", True, "remote", 8 * D, None), 58),
]

SEARCH3_JOBS: list[JobSpec] = [
    ("Data Analyst", "Brisa Dados", "São Paulo, SP", "linkedin", False, "hybrid", 1 * D, None),
    ("Analista de Dados", "Casa Verde", "Curitiba, PR", "indeed", False, "onsite", 3 * D, None),
    ("BI Analyst", "Orla", "Belo Horizonte, MG", "indeed", False, "onsite", 5 * D, None),
]
# fmt: on


def _job(session: Session, spec: JobSpec, n: int, searched_region: str | None = "Brazil") -> Job:
    title, company, location, source, remote, mode, age, salary = spec
    now = utcnow()
    description = f"{title} at {company}. Work model: {mode}. Python, LangChain and RAG."
    job = Job(
        source=source,
        external_id=f"demo-{n}",
        title=title,
        company=company,
        location=location,
        remote=remote,
        url=f"https://example.com/jobs/demo-{n}",
        description=description,
        salary_min=salary[0] if salary else None,
        salary_max=salary[1] if salary else None,
        salary_currency=salary[2] if salary else None,
        tags=["python"],
        posted_at=now - age,
        first_seen_at=now - age,
        last_seen_at=now,
        content_hash=content_hash(title, description),
        fingerprint=fingerprint(title, company, location),
        raw={"searched_region": searched_region} if searched_region else {},
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _match(
    session: Session, job: Job, search: Search, score: int | None, status: str = "new"
) -> None:
    assert job.id is not None and search.id is not None
    scored = score is not None
    session.add(
        Match(
            job_id=job.id,
            search_id=search.id,
            user_id=search.user_id,
            similarity=0.5 + score / 200 if score is not None else 0.18,
            score=score,
            reasoning=(
                "Strong fit: the role asks for Python, LangChain and RAG, all in your "
                "profile, and is open to candidates in Brazil."
                if scored
                else None
            ),
            matched_skills=["Python", "LangChain", "RAG"] if scored else [],
            missing_skills=["Kubernetes"] if scored else [],
            red_flags=["Requires English for daily meetings"] if scored else [],
            status=status,
            llm_model=MODEL if scored else None,
        )
    )
    session.commit()


def _sources(*rows: tuple[str, str, int, int, int, str]) -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "state": state,
            "fetched": fetched,
            "queries_done": done,
            "queries_total": total,
            "detail": detail,
        }
        for name, state, fetched, done, total, detail in rows
    ]


def _run(
    session: Session,
    search: Search,
    started: datetime,
    finished: datetime | None,
    counters: dict[str, int],
    sources: list[dict[str, object]],
) -> None:
    session.add(
        Run(
            job="search",
            user_id=search.user_id,
            search_id=search.id,
            started_at=started,
            finished_at=finished,
            ok=finished is not None,
            counters=counters,
            sources=sources,
        )
    )
    session.commit()


def _conversation(paragraph: str, reading: ExtractedProfile, **answers: Answer) -> Conversation:
    c = conv.with_reading(Conversation(paragraph=paragraph), reading)
    for qid, a in answers.items():
        question: QuestionId = qid  # type: ignore[assignment]
        c = conv.answer(c, question, a)
    return c


def _stamp(session: Session, search: Search, title: str, age: timedelta) -> None:
    """Name the search and place it in the sidebar. Saving a conversation derives a title."""
    search.title = title
    search.last_used_at = utcnow() - age
    session.add(search)
    session.commit()


def _counters(fetched: int, ok: int, failed: int, evaluated: int, remaining: int) -> dict[str, int]:
    return {
        "fetched": fetched,
        "sources_ok": ok,
        "sources_failed": failed,
        "candidates": evaluated + remaining,
        "evaluated": evaluated,
        "remaining": remaining,
        "scored": evaluated,
        "to_score": evaluated + remaining,
    }


def _confirmed(
    session: Session,
    settings: Settings,
    user_id: int,
    title: str,
    paragraph: str,
    reading: ExtractedProfile,
    **answers: Answer,
) -> Search:
    search = add_search(session, user_id, title)
    save_conversation(session, search, _conversation(paragraph, reading, **answers))
    assert search.id is not None
    confirm(session, settings, user_id, search.id)
    return search


def _seed_search1(session: Session, settings: Settings, user_id: int) -> list[Job]:
    search = _confirmed(
        session,
        settings,
        user_id,
        "Junior AI Engineer",
        "I am a junior AI engineer in Brazil. I want remote or hybrid work with Python.",
        ExtractedProfile(
            terms=["ai engineer", "python"],
            seniority=["junior"],
            required_skills=["Python", "LangChain"],
            stated_work_modes=["remote", "hybrid"],
            stated_regions=["Brazil"],
        ),
        city=Answer(choice="anywhere"),
    )
    assert search.id is not None
    jobs: list[Job] = []
    for n, (spec, score) in enumerate(SEARCH1_JOBS):
        job = _job(session, spec, n)
        jobs.append(job)
        status = "saved" if n in (0, 2) else "applied" if n == 12 else "new"
        _match(session, job, search, score, status)
    waiting = [_job(session, spec, 100 + n) for n, spec in enumerate(SEARCH1_WAITING)]
    record_fetched(session, search.id, [j.id or 0 for j in [*jobs, *waiting]])
    now = utcnow()
    _run(
        session,
        search,
        now - 2 * D - 10 * MIN,
        now - 2 * D,
        _counters(22, 4, 0, 13, 9),
        _sources(
            ("linkedin", "done", 9, 2, 2, ""),
            ("indeed", "done", 4, 2, 2, ""),
            ("himalayas", "done", 5, 1, 1, ""),
            ("remotive", "done", 3, 1, 1, ""),
        ),
    )
    _stamp(session, search, "Junior AI Engineer", 1 * H)
    return jobs


def _seed_search2(session: Session, settings: Settings, user_id: int, shared: Job) -> None:
    search = _confirmed(
        session,
        settings,
        user_id,
        "Remote Python backend",
        "Remote Python backend work, junior, in Brazil.",
        ExtractedProfile(
            terms=["python backend"],
            seniority=["junior"],
            required_skills=["Python"],
            stated_work_modes=["remote"],
            stated_regions=["Brazil"],
        ),
    )
    assert search.id is not None
    jobs = [_job(session, spec, 200 + n) for n, (spec, _) in enumerate(SEARCH2_JOBS)]
    for job, (_, score) in zip(jobs, SEARCH2_JOBS, strict=True):
        _match(session, job, search, score)
    _match(session, shared, search, SHARED_SCORE_IN_SEARCH2)
    record_fetched(session, search.id, [j.id or 0 for j in [*jobs, shared]])
    now = utcnow()
    _run(
        session,
        search,
        now - 3 * D - 8 * MIN,
        now - 3 * D,
        _counters(5, 3, 0, 5, 0),
        _sources(
            ("remotive", "done", 2, 1, 1, ""),
            ("himalayas", "done", 2, 1, 1, ""),
            ("linkedin", "done", 1, 1, 1, ""),
        ),
    )
    _stamp(session, search, "Remote Python backend", 1 * D)


def _seed_search3(session: Session, settings: Settings, user_id: int) -> None:
    search = _confirmed(
        session,
        settings,
        user_id,
        "Data analyst for a friend",
        "A friend wants a junior data analyst job, on-site, in Recife.",
        ExtractedProfile(
            terms=["data analyst"],
            seniority=["junior"],
            required_skills=["SQL"],
            stated_work_modes=["onsite"],
            stated_regions=["Brazil", "Recife"],
        ),
    )
    assert search.id is not None
    jobs = [
        _job(session, spec, 300 + n, searched_region=None) for n, spec in enumerate(SEARCH3_JOBS)
    ]
    for job in jobs:
        _match(session, job, search, None, "low")  # the cosine prefilter turned them down
    record_fetched(session, search.id, [j.id or 0 for j in jobs])
    now = utcnow()
    _run(
        session,
        search,
        now - 4 * D - 3 * MIN,
        now - 4 * D,
        _counters(3, 1, 1, 0, 0),
        _sources(
            ("linkedin", "done", 3, 1, 1, ""),
            ("indeed", "failed", 0, 0, 1, "SourceBlocked: 429 Too Many Requests"),
        ),
    )
    _stamp(session, search, "Data analyst for a friend", 2 * D)


def _seed_search4(session: Session, user_id: int) -> None:
    """Stops mid-conversation: the work mode is answered, the location question is open."""
    search = add_search(session, user_id, "Frontend in Lisbon")
    c = _conversation(
        "Mid-level frontend developer, React and TypeScript, Lisbon.",
        ExtractedProfile(
            terms=["frontend developer", "react"],
            seniority=["mid"],
            required_skills=["React", "TypeScript"],
            stated_regions=["Lisbon"],
        ),
        work_modes=Answer(choice="pick", values=["remote"]),
    )
    assert conv.pending(c) == ["location"], conv.pending(c)
    save_conversation(session, search, c)
    _stamp(session, search, "Frontend in Lisbon", 3 * D)


def _seed_search5(session: Session, settings: Settings, user_id: int) -> None:
    """Confirmed, but its run was killed: no finish time and ``ok`` still false."""
    search = _confirmed(
        session,
        settings,
        user_id,
        "Data engineer",
        "Mid-level data engineer, remote, based in Portugal.",
        ExtractedProfile(
            terms=["data engineer"],
            seniority=["mid"],
            required_skills=["SQL", "Python"],
            stated_work_modes=["remote"],
            stated_regions=["Portugal"],
        ),
    )
    _run(
        session,
        search,
        utcnow() - 40 * MIN,
        None,
        {"fetched": 18},
        _sources(
            ("linkedin", "done", 18, 2, 2, ""),
            ("indeed", "searching", 0, 1, 2, ""),
            ("himalayas", "waiting", 0, 0, 1, ""),
        ),
    )
    _stamp(session, search, "Data engineer", 4 * D)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python scripts/seed_demo.py <path.db>", file=sys.stderr)
        return 2
    path = Path(argv[0])
    if path.exists():
        print(f"{path} already exists; pick a new file.", file=sys.stderr)
        return 1
    url = f"sqlite:///{path.resolve().as_posix()}"
    engine = create_engine_from_url(url)
    init_db(engine)
    settings = Settings()
    with Session(engine) as session:
        user = get_or_create_default_user(session)
        assert user.id is not None
        jobs = _seed_search1(session, settings, user.id)
        shared = next(job for job in jobs if job.title == SHARED_TITLE)
        _seed_search2(session, settings, user.id, shared)
        _seed_search3(session, settings, user.id)
        _seed_search4(session, user.id)
        _seed_search5(session, settings, user.id)
    engine.dispose()
    print(f"Demo database written to {path}. Serve it with:")
    print(f"  DATABASE_URL={url} SCHEDULER_ENABLED=false GOOGLE_API_KEY=demo uv run jobscout serve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

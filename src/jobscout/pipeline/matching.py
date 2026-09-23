"""Select what deserves an LLM call, run the graph on it, persist the result.

Selection lives here (not in the graph) so the batch embedding call and the top-K ranking
happen once per run instead of once per job.
"""

import logging
from dataclasses import dataclass, field

from langchain_core.embeddings import Embeddings
from sqlmodel import Session, col, select

from jobscout.config import Settings
from jobscout.matching.graph import GraphDeps, build_graph
from jobscout.matching.llm import chat_model, embeddings
from jobscout.matching.prompts import build_user_prompt, job_text, profile_text
from jobscout.matching.schemas import MatchState
from jobscout.matching.vectors import cosine, dim, pack, unpack
from jobscout.models import Job, Match, User, UserPreferences
from jobscout.pipeline.filters import job_matches_preferences
from jobscout.pipeline.users import get_preferences

log = logging.getLogger(__name__)

_EMBED_CHUNK = 100


@dataclass
class MatchRun:
    candidates: int = 0
    evaluated: int = 0
    skipped_low: int = 0
    errors: list[str] = field(default_factory=list)
    error: str | None = None
    previewed: list[tuple[int, float, str]] = field(default_factory=list)


def select_candidates(session: Session, prefs: UserPreferences, user_id: int) -> list[Job]:
    """Active jobs passing the deterministic filter that have no match, or a stale one."""
    existing: dict[int, str] = {
        match.job_id: match.status
        for match in session.exec(select(Match).where(Match.user_id == user_id)).all()
    }
    jobs = session.exec(select(Job).where(col(Job.is_active).is_(True))).all()
    return [
        job
        for job in jobs
        if job.id is not None
        and existing.get(job.id, "stale") == "stale"
        and job_matches_preferences(job, prefs)
    ]


def _ensure_profile_embedding(
    session: Session, prefs: UserPreferences, embed: Embeddings, wanted_dim: int
) -> list[float]:
    if prefs.profile_embedding is not None and dim(prefs.profile_embedding) == wanted_dim:
        return unpack(prefs.profile_embedding)
    vector = embed.embed_query(profile_text(prefs))
    prefs.profile_embedding = pack(vector)
    session.add(prefs)
    session.commit()
    return vector


def _ensure_job_embeddings(
    session: Session, jobs: list[Job], embed: Embeddings, wanted_dim: int
) -> dict[int, list[float]]:
    vectors: dict[int, list[float]] = {}
    missing: list[Job] = []
    for job in jobs:
        if job.id is None:
            continue
        if job.embedding is not None and dim(job.embedding) == wanted_dim:
            vectors[job.id] = unpack(job.embedding)
        else:
            missing.append(job)

    for start in range(0, len(missing), _EMBED_CHUNK):
        chunk = missing[start : start + _EMBED_CHUNK]
        computed = embed.embed_documents([job_text(job) for job in chunk])
        for job, vector in zip(chunk, computed, strict=True):
            assert job.id is not None
            job.embedding = pack(vector)
            vectors[job.id] = vector
            session.add(job)
    if missing:
        session.commit()
    return vectors


def _upsert_match(session: Session, job_id: int, user_id: int, **values: object) -> None:
    match = session.exec(
        select(Match).where(Match.job_id == job_id, Match.user_id == user_id)
    ).first()
    if match is None:
        match = Match(job_id=job_id, user_id=user_id, similarity=0.0)
    for name, value in values.items():
        setattr(match, name, value)
    session.add(match)


def _default_deps(settings: Settings) -> GraphDeps:
    return GraphDeps(
        chat=chat_model(settings),
        embed=embeddings(settings),
        threshold=settings.similarity_threshold,
        model_name=settings.llm_model,
    )


def run_match(
    session: Session,
    settings: Settings,
    user_id: int,
    limit: int | None = None,
    dry_run: bool = False,
    deps: GraphDeps | None = None,
) -> MatchRun:
    """Evaluate the best unmatched candidates for one user, bounded by the per-run cap."""
    result = MatchRun()
    prefs = get_preferences(session, user_id)
    if not prefs.profile_summary.strip():
        result.error = "No profile summary set — nothing to match against."
        return result

    candidates = select_candidates(session, prefs, user_id)
    result.candidates = len(candidates)
    if not candidates:
        return result

    embed = deps.embed if deps is not None else embeddings(settings)
    wanted_dim = settings.embedding_dim
    profile_vector = _ensure_profile_embedding(session, prefs, embed, wanted_dim)
    # The profile embedding fixes the dimension the job vectors must match.
    wanted_dim = len(profile_vector)
    job_vectors = _ensure_job_embeddings(session, candidates, embed, wanted_dim)

    ranked = sorted(
        (
            (cosine(job_vectors[job.id], profile_vector), job)
            for job in candidates
            if job.id is not None and job.id in job_vectors
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    cap = limit if limit is not None else settings.max_llm_evaluations_per_run
    selected = ranked[:cap]

    if dry_run:
        result.previewed = [
            (job.id, similarity, job.title) for similarity, job in selected if job.id is not None
        ]
        return result

    user = session.get(User, user_id)
    locale = user.locale if user is not None else "en"
    graph_deps = deps if deps is not None else _default_deps(settings)
    graph = build_graph(graph_deps)

    for _similarity, job in selected:
        assert job.id is not None
        state: MatchState = {
            "job_id": job.id,
            "user_id": user_id,
            "job_text": job_text(job),
            "prompt": build_user_prompt(prefs, job, locale),
            "profile_text": profile_text(prefs),
            "job_embedding": job_vectors[job.id],
            "profile_embedding": profile_vector,
            "min_score": prefs.min_score_to_notify,
        }
        try:
            final = graph.invoke(state)

            evaluation = final.get("evaluation")
            if evaluation is None:
                _upsert_match(
                    session,
                    job.id,
                    user_id,
                    similarity=final["similarity"],
                    score=None,
                    reasoning=None,
                    matched_skills=[],
                    missing_skills=[],
                    red_flags=[],
                    status="low",
                    llm_model=None,
                )
                was_low = True
            else:
                _upsert_match(
                    session,
                    job.id,
                    user_id,
                    similarity=final["similarity"],
                    score=evaluation.score,
                    reasoning=evaluation.reasoning,
                    matched_skills=evaluation.matched_skills,
                    missing_skills=evaluation.missing_skills,
                    red_flags=evaluation.red_flags,
                    status="new",
                    llm_model=final.get("llm_model"),
                )
                was_low = False
            session.commit()
        except Exception as exc:  # isolate one bad job from the rest of the run
            session.rollback()
            log.error("matching failed for job %s: %s: %s", job.id, type(exc).__name__, exc)
            result.errors.append(f"job {job.id}: {type(exc).__name__}: {exc}")
            continue

        # Only reachable once the row is durably committed — a commit failure above
        # jumps to `except` and `continue`s before either counter can move.
        if was_low:
            result.skipped_low += 1
        else:
            result.evaluated += 1

    return result

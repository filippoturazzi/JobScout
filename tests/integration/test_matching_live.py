"""Hits the real provider. Run explicitly: `uv run pytest -m integration`.

Needs GOOGLE_API_KEY (or the configured provider's key) and jobs in the database.
"""

import os

import pytest
from sqlmodel import Session, col, select

from jobscout.config import get_settings
from jobscout.db import get_engine, init_db
from jobscout.matching.llm import chat_model, embeddings
from jobscout.matching.prompts import job_text, profile_text
from jobscout.matching.schemas import EvaluationResult
from jobscout.matching.vectors import cosine
from jobscout.models import Job
from jobscout.pipeline.users import get_or_create_default_user, update_preferences

pytestmark = pytest.mark.integration

PROFILE = "Junior AI engineer. Python, FastAPI, LLM applications, LangGraph. Remote, Europe."


@pytest.fixture
def live_session():
    settings = get_settings()
    if not os.environ.get("GOOGLE_API_KEY") and settings.llm_provider == "google":
        pytest.skip("GOOGLE_API_KEY not set")
    engine = get_engine(settings)
    init_db(engine)
    with Session(engine) as session:
        yield session


def test_live_evaluation_and_similarity_distribution(live_session, capsys):
    settings = get_settings()
    jobs = live_session.exec(select(Job).where(col(Job.is_active).is_(True)).limit(30)).all()
    if not jobs:
        pytest.skip("no jobs in the database; run `jobscout fetch` first")

    user = get_or_create_default_user(live_session)
    prefs, _ = update_preferences(live_session, user.id, {"profile_summary": PROFILE})

    embedder = embeddings(settings)
    profile_vector = embedder.embed_query(profile_text(prefs))
    job_vectors = embedder.embed_documents([job_text(job) for job in jobs])
    similarities = sorted(
        (cosine(vector, profile_vector), job.title)
        for vector, job in zip(job_vectors, jobs, strict=True)
    )

    with capsys.disabled():
        print(f"\nembedding dim: {len(profile_vector)}  model: {settings.embedding_model}")
        print(f"min={similarities[0][0]:.3f}  max={similarities[-1][0]:.3f}")
        print("top 5:")
        for score, title in reversed(similarities[-5:]):
            print(f"  {score:.3f}  {title}")
        print("bottom 3:")
        for score, title in similarities[:3]:
            print(f"  {score:.3f}  {title}")

    best_title = similarities[-1][1]
    best_job = next(job for job in jobs if job.title == best_title)
    structured = chat_model(settings).with_structured_output(EvaluationResult)
    evaluation = structured.invoke(
        [("system", "Score the fit 0-100."), ("human", f"{PROFILE}\n\n{job_text(best_job)}")]
    )

    assert isinstance(evaluation, EvaluationResult)
    assert 0 <= evaluation.score <= 100
    assert evaluation.reasoning.strip()

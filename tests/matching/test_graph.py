from langchain_core.embeddings import DeterministicFakeEmbedding

from jobscout.matching.graph import GraphDeps, build_graph
from jobscout.matching.schemas import EvaluationResult
from tests.matching.fakes import CountingChatModel

DIM = 8


def _deps(chat: CountingChatModel, threshold: float) -> GraphDeps:
    return GraphDeps(
        chat=chat,  # type: ignore[arg-type]
        embed=DeterministicFakeEmbedding(size=DIM),
        threshold=threshold,
        model_name="fake-model",
    )


def _state(**kw):
    base = {
        "job_id": 1,
        "user_id": 1,
        "job_text": "Python LLM engineer in Berlin",
        "profile_text": "Python LLM engineer",
        "profile_embedding": DeterministicFakeEmbedding(size=DIM).embed_query(
            "Python LLM engineer"
        ),
    }
    base.update(kw)
    return base


def test_low_similarity_skips_the_llm():
    chat = CountingChatModel()
    graph = build_graph(_deps(chat, threshold=1.1))  # nothing can clear this

    final = graph.invoke(_state())

    assert chat.calls == 0
    assert final["evaluation"] is None
    assert final["should_notify"] is False
    assert "similarity" in final


def test_high_similarity_evaluates_and_decides():
    chat = CountingChatModel(
        results=[
            EvaluationResult(score=90, reasoning="Strong fit.", matched_skills=["Python"]),
        ]
    )
    graph = build_graph(_deps(chat, threshold=-1.0))  # everything clears this

    final = graph.invoke(_state())

    assert chat.calls == 1
    evaluation = final["evaluation"]
    assert evaluation is not None and evaluation.score == 90
    assert final["llm_model"] == "fake-model"


def test_embed_job_uses_the_cached_vector():
    chat = CountingChatModel()
    graph = build_graph(_deps(chat, threshold=-1.0))
    cached = [1.0] * DIM

    final = graph.invoke(_state(job_embedding=cached))

    assert final["job_embedding"] == cached


def test_identical_texts_score_similarity_one():
    chat = CountingChatModel()
    graph = build_graph(_deps(chat, threshold=-1.0))
    text = "Python LLM engineer"
    profile = DeterministicFakeEmbedding(size=DIM).embed_query(text)

    final = graph.invoke(_state(job_text=text, profile_text=text, profile_embedding=profile))

    assert final["similarity"] > 0.999

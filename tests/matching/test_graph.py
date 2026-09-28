from jobscout.matching.graph import GraphDeps, build_graph
from jobscout.matching.schemas import EvaluationResult
from tests.matching.fakes import CountingChatModel, DeterministicFakeEmbedding

DIM = 8


def _deps(chat: CountingChatModel, threshold: float) -> GraphDeps:
    return GraphDeps(
        chat=chat,  # type: ignore[arg-type]
        embed=DeterministicFakeEmbedding(size=DIM),  # type: ignore[arg-type]
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


def test_decide_uses_the_users_notify_threshold():
    chat = CountingChatModel(results=[EvaluationResult(score=65, reasoning="Partial fit.")])
    graph = build_graph(_deps(chat, threshold=-1.0))

    below = graph.invoke(_state(min_score=70))
    assert below["should_notify"] is False

    chat_high = CountingChatModel(results=[EvaluationResult(score=90, reasoning="Strong fit.")])
    above = build_graph(_deps(chat_high, threshold=-1.0)).invoke(_state(min_score=70))
    assert above["should_notify"] is True


def test_a_missing_notify_threshold_fails_closed():
    """A caller that forgets `min_score` must not notify on everything (stage 4 reads this)."""
    chat = CountingChatModel(results=[EvaluationResult(score=100, reasoning="Perfect fit.")])
    graph = build_graph(_deps(chat, threshold=-1.0))

    final = graph.invoke(_state())  # no min_score in the state

    assert final["evaluation"] is not None
    assert final["should_notify"] is False


def test_the_fallback_embed_uses_the_short_text_not_the_prompt_text():
    """Both embed paths must agree on the input, or their vectors are not comparable."""
    seen: list[str] = []

    class _Recording(DeterministicFakeEmbedding):
        def embed_query(self, text: str) -> list[float]:
            seen.append(text)
            return super().embed_query(text)

    deps = GraphDeps(
        chat=CountingChatModel(),  # type: ignore[arg-type]
        embed=_Recording(size=8),  # type: ignore[arg-type]
        threshold=-1.0,
        model_name="fake",
    )
    graph = build_graph(deps)

    graph.invoke(
        {
            "job_id": 1,
            "user_id": 1,
            "job_text": "LONG prompt text with lots of boilerplate",
            "job_embedding_text": "SHORT role text",
            "profile_embedding": DeterministicFakeEmbedding(size=8).embed_query("p"),
            "min_score": 0,
        }
    )

    assert seen == ["SHORT role text"]

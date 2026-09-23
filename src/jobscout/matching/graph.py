"""The per-(job, user) matching graph.

    embed_job ─► prefilter ─(below threshold)─► record_low ─► END
                       └────(at or above)─────► evaluate ─► decide ─► END

The conditional edge is the cost control: a job that does not clear the cosine floor never
reaches the LLM. Persistence happens in ``pipeline.matching``; this module stays I/O-free
apart from the model calls it is handed.
"""

from dataclasses import dataclass
from typing import Literal, cast

from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from jobscout.matching.prompts import SYSTEM_PROMPT
from jobscout.matching.schemas import EvaluationResult, MatchState
from jobscout.matching.vectors import cosine


@dataclass
class GraphDeps:
    """Everything the nodes need, injected so tests can pass doubles."""

    chat: BaseChatModel
    embed: Embeddings
    threshold: float
    model_name: str


def build_graph(deps: GraphDeps) -> CompiledStateGraph[MatchState]:
    """Compile the matching graph. Returns a LangGraph ``CompiledStateGraph``."""

    def embed_job(state: MatchState) -> MatchState:
        if state.get("job_embedding"):
            return {}
        vector = deps.embed.embed_query(state["job_text"])
        return {"job_embedding": vector}

    def prefilter(state: MatchState) -> MatchState:
        similarity = cosine(state["job_embedding"], state["profile_embedding"])
        return {"similarity": similarity}

    def route(state: MatchState) -> Literal["record_low", "evaluate"]:
        return "evaluate" if state["similarity"] >= deps.threshold else "record_low"

    def record_low(state: MatchState) -> MatchState:
        # `state` is unused here, but must be named `state` (not `_state`): mypy checks a
        # node callable against LangGraph's callback protocol by parameter name, not just
        # position, since the parameter isn't marked positional-only.
        return {"evaluation": None, "llm_model": None, "should_notify": False}

    def evaluate(state: MatchState) -> MatchState:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            # `prompt` carries profile + job (pipeline.matching builds it); `job_text`
            # alone is the standalone fallback that keeps the graph runnable on its own.
            HumanMessage(content=state.get("prompt") or state["job_text"]),
        ]
        structured = deps.chat.with_structured_output(EvaluationResult)
        # `with_structured_output` is typed to return `dict[str, Any] | BaseModel` because it
        # also accepts dict/JSON schemas; passing a pydantic class always yields an instance
        # of that class at runtime.
        evaluation = cast(EvaluationResult, structured.invoke(messages))
        return {"evaluation": evaluation, "llm_model": deps.model_name}

    def decide(state: MatchState) -> MatchState:
        evaluation = state.get("evaluation")
        threshold = state.get("min_score", 0)
        return {"should_notify": evaluation is not None and evaluation.score >= threshold}

    builder = StateGraph(MatchState)
    builder.add_node("embed_job", embed_job)
    builder.add_node("prefilter", prefilter)
    builder.add_node("record_low", record_low)
    builder.add_node("evaluate", evaluate)
    builder.add_node("decide", decide)

    builder.add_edge(START, "embed_job")
    builder.add_edge("embed_job", "prefilter")
    builder.add_conditional_edges("prefilter", route)
    builder.add_edge("record_low", END)
    builder.add_edge("evaluate", "decide")
    builder.add_edge("decide", END)

    return builder.compile()
